"""Regression tests for multi-persona audit v1.2.1 findings.

Source: ``reports/external/multi-persona-audit-v1.2.1-2026-04-10.md``

Covers every CRIT/HIGH finding that the engineering team can reproduce
against the in-process test client:

* **CRIT-2/3/4** — ``/v1/batch`` bypasses ownership, admin gate, and
  input-schema validation (enumeration + privilege escalation).
* **HIGH-1** — ``X-API-Key`` header is accepted but undocumented.
* **HIGH-2** — Refund silently retains gateway fee (no disclosure).
* **HIGH-3** — Payment ``gateway_fee`` returned with 4-decimal float
  leakage (``"0.0246"``) instead of 2-decimal Decimal.
* **HIGH-4** — ``POST /v1/disputes`` 500 when legacy DB lacks the
  ``deadline_at`` / ``respondent`` columns.
* **HIGH-5** — ``POST /v1/billing/wallets/{id}/convert`` returns 500 for
  non-credits currency pairs (e.g. USD→ETH) instead of routing via
  CREDITS.
* **HIGH-6** — ``POST /v1/infra/webhooks`` 500 when legacy DB lacks the
  ``filter_agent_ids`` column.

Each test is standalone — no shared state — so they can also serve as
permanent BOLA/regression fixtures.
"""

from __future__ import annotations

from decimal import Decimal

import aiosqlite
import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# CRIT-2/3/4 — /v1/batch bypass
# ---------------------------------------------------------------------------


class TestBatchOwnershipBypass:
    """A free-tier caller must not be able to enumerate or act on another
    agent's resources by routing tool calls through ``/v1/batch``.
    """

    async def test_batch_rejects_cross_agent_list_api_keys(self, client, app):
        """BOLA: caller=alice, params.agent_id=bob → must fail (403)."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("alice-batch", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.wallet.create("bob-batch", initial_balance=100.0, signup_bonus=False)
        alice_key_info = await ctx.key_manager.create_key("alice-batch", tier="free")
        await ctx.key_manager.create_key("bob-batch", tier="free")
        alice_key = alice_key_info["key"]

        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "list_api_keys", "params": {"agent_id": "bob-batch"}},
                ]
            },
            headers={"Authorization": f"Bearer {alice_key}"},
        )
        assert resp.status_code == 200, resp.text  # batch always 200, per-call errors inline
        body = resp.json()
        first = body["results"][0]
        assert first["success"] is False, (
            "CRIT-2: cross-agent list_api_keys via /v1/batch must be rejected"
        )
        assert first["error"]["code"] in {"forbidden", "authorization_denied"}

    async def test_batch_rejects_cross_agent_get_balance(self, client, app):
        """BOLA: caller=alice, params.agent_id=bob → must fail."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("alice2-batch", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.wallet.create("bob2-batch", initial_balance=100.0, signup_bonus=False)
        alice_key_info = await ctx.key_manager.create_key("alice2-batch", tier="free")
        alice_key = alice_key_info["key"]

        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "get_balance", "params": {"agent_id": "bob2-batch"}},
                ]
            },
            headers={"Authorization": f"Bearer {alice_key}"},
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()["results"][0]
        assert first["success"] is False
        assert first["error"]["code"] in {"forbidden", "authorization_denied"}

    async def test_batch_blocks_admin_only_tools_for_non_admin(self, client, app):
        """Non-admin callers cannot reach ``ADMIN_ONLY_TOOLS`` via ``/v1/batch``."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("free-admin-batch", initial_balance=500.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("free-admin-batch", tier="free")

        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "backup_database", "params": {"database": "billing"}},
                ]
            },
            headers={"Authorization": f"Bearer {key_info['key']}"},
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()["results"][0]
        assert first["success"] is False
        assert first["error"]["code"] in {"admin_only", "forbidden", "insufficient_tier"}

    async def test_batch_allows_caller_own_resources(self, client, api_key):
        """Regression: ``/v1/batch`` still works when caller acts on own resources."""
        resp = await client.post(
            "/v1/batch",
            json={
                "calls": [
                    {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
                ]
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()["results"][0]
        assert first["success"] is True, first


# ---------------------------------------------------------------------------
# HIGH-4 — /v1/disputes 500 from legacy disputes DB missing columns
# ---------------------------------------------------------------------------


class TestDisputeSchemaMigration:
    """``DisputeEngine.connect()`` must migrate legacy DBs that predate the
    ``deadline_at`` / ``respondent`` / ``response`` / ``resolution`` columns.
    """

    async def test_connect_adds_missing_columns_to_legacy_disputes_table(self, tmp_path):
        from gateway.src.disputes import DisputeEngine

        db_file = tmp_path / "legacy_disputes.db"
        # Create the pre-migration schema (no deadline_at, no respondent, etc.)
        async with aiosqlite.connect(db_file) as legacy:
            await legacy.execute(
                """
                CREATE TABLE disputes (
                    id TEXT PRIMARY KEY,
                    escrow_id TEXT NOT NULL,
                    opener TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at REAL NOT NULL
                )
                """
            )
            await legacy.commit()

        engine = DisputeEngine(dsn=f"sqlite:///{db_file}", payment_engine=None)
        await engine.connect()
        try:
            assert engine.db is not None
            cursor = await engine.db.execute("PRAGMA table_info(disputes)")
            cols = {row[1] for row in await cursor.fetchall()}
        finally:
            await engine.close()

        # All new columns added by the migration must be present:
        for col in (
            "respondent",
            "response",
            "resolution",
            "resolved_by",
            "notes",
            "responded_at",
            "resolved_at",
            "deadline_at",
        ):
            assert col in cols, f"HIGH-4: legacy disputes DB missing '{col}' after connect()"


# ---------------------------------------------------------------------------
# HIGH-6 — /v1/infra/webhooks 500 from legacy webhooks DB missing columns
# ---------------------------------------------------------------------------


class TestWebhookSchemaMigration:
    """``WebhookManager.connect()`` must migrate legacy DBs that predate
    the ``filter_agent_ids`` column.
    """

    async def test_connect_adds_missing_filter_column_to_legacy_webhooks_table(self, tmp_path):
        from gateway.src.webhooks import WebhookManager

        db_file = tmp_path / "legacy_webhooks.db"
        async with aiosqlite.connect(db_file) as legacy:
            await legacy.execute(
                """
                CREATE TABLE webhooks (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    event_types TEXT NOT NULL,
                    secret TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            await legacy.commit()

        mgr = WebhookManager(dsn=f"sqlite:///{db_file}")
        await mgr.connect()
        try:
            db = mgr._require_db()  # type: ignore[attr-defined]
            cursor = await db.execute("PRAGMA table_info(webhooks)")
            cols = {row[1] for row in await cursor.fetchall()}
        finally:
            await mgr.close()

        assert "filter_agent_ids" in cols, (
            "HIGH-6: legacy webhooks DB missing 'filter_agent_ids' after connect()"
        )


# ---------------------------------------------------------------------------
# HIGH-5 — convert USD→ETH 500 (no multi-hop rate)
# ---------------------------------------------------------------------------


class TestCrossCurrencyConvertMultiHop:
    """``ExchangeRateService.get_rate`` must route cross-currency pairs
    via the CREDITS pivot so USD→ETH works without a direct row.
    """

    async def test_get_rate_routes_usd_to_eth_via_credits(self, tmp_path):
        from billing_src.exchange import ExchangeRateService
        from billing_src.models import Currency
        from billing_src.storage import StorageBackend

        storage = StorageBackend(f"sqlite:///{tmp_path / 'billing.db'}")
        await storage.connect()
        try:
            svc = ExchangeRateService(storage=storage)
            await svc.initialize_default_rates()
            rate = await svc.get_rate(Currency("USD"), Currency("ETH"))
        finally:
            await storage.close()

        # USD→CREDITS = 100; ETH→CREDITS = 400000 → USD→ETH = 100/400000 = 0.00025
        assert rate > 0
        assert abs(float(rate) - (100.0 / 400000.0)) < 1e-9, (
            f"HIGH-5: expected USD→ETH ≈ 0.00025, got {rate}"
        )


# ---------------------------------------------------------------------------
# HIGH-1 — X-API-Key header must be documented in OpenAPI security schemes
# ---------------------------------------------------------------------------


class TestApiKeyHeaderDocumented:
    """``X-API-Key`` is an accepted auth header and must appear in
    ``components.securitySchemes`` of the served OpenAPI document so
    clients know it is supported.
    """

    async def test_openapi_documents_x_api_key_security_scheme(self, client):
        resp = await client.get("/v1/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        schemes = spec.get("components", {}).get("securitySchemes", {})
        scheme_values = list(schemes.values())
        names = [s.get("name", "").lower() for s in scheme_values if isinstance(s, dict)]
        assert any(n == "x-api-key" for n in names), (
            f"HIGH-1: X-API-Key security scheme missing from OpenAPI; got {schemes!r}"
        )


# ---------------------------------------------------------------------------
# HIGH-3 — gateway_fee decimal formatting (end-to-end Decimal, 2 dp)
# ---------------------------------------------------------------------------


class TestGatewayFeeDecimalFormatting:
    """``gateway_fee`` must always be a 2-decimal string, never leaking
    float representation like ``"0.0246"`` or losing trailing zero like ``"5.0"``.
    """

    async def test_create_intent_fee_is_2dp_for_small_amount(self, client, api_key, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-fee", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "test-agent",
                "payee": "payee-fee",
                "amount": "1.23",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        fee = body.get("gateway_fee")
        assert isinstance(fee, str), f"HIGH-3: gateway_fee must be a string, got {type(fee).__name__}"
        # Must be parseable as Decimal with exactly 2 decimal places
        d = Decimal(fee)
        assert d == d.quantize(Decimal("0.01")), (
            f"HIGH-3: gateway_fee must have exactly 2 decimal places, got {fee!r}"
        )
        assert "." in fee and len(fee.split(".")[1]) == 2, (
            f"HIGH-3: gateway_fee must print with 2 decimal places, got {fee!r}"
        )

    async def test_create_intent_fee_preserves_trailing_zero(self, client, api_key, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-fee2", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "test-agent",
                "payee": "payee-fee2",
                "amount": "250.00",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201, resp.text
        fee = resp.json()["gateway_fee"]
        # 2% of 250 = 5.00 — must NOT be "5.0"
        assert fee == "5.00", f"HIGH-3: expected '5.00', got {fee!r}"


# ---------------------------------------------------------------------------
# HIGH-2 — Refund must disclose whether the gateway fee was refunded
# ---------------------------------------------------------------------------


class TestRefundFeeDisclosure:
    """When a settled intent is refunded, the response body must tell the
    integrator whether the 2% gateway fee was also refunded. Silently
    retaining the fee with no signal is a reconciliation bug (HIGH-2).
    """

    async def test_refund_response_has_fee_refunded_field(self, client, api_key, app):
        ctx = app.state.ctx
        # Create payee + fund payer enough to cover fees
        await ctx.tracker.wallet.create("payee-refund", initial_balance=0.0, signup_bonus=False)
        # test-agent starts with 1000 credits from api_key fixture

        # Create intent
        create = await client.post(
            "/v1/payments/intents",
            json={"payer": "test-agent", "payee": "payee-refund", "amount": "50.00"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert create.status_code == 201, create.text
        intent_id = create.json()["id"]

        # Capture
        cap = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            json={},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert cap.status_code == 200, cap.text

        # Refund full
        ref = await client.post(
            f"/v1/payments/intents/{intent_id}/refund",
            json={"amount": "50.00"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert ref.status_code == 200, ref.text
        body = ref.json()
        assert "fee_refunded" in body, (
            f"HIGH-2: refund response must disclose 'fee_refunded' flag; got keys: {list(body.keys())}"
        )
        assert "fee_retained" in body, (
            f"HIGH-2: refund response must disclose 'fee_retained' amount; got keys: {list(body.keys())}"
        )


# ---------------------------------------------------------------------------
# CRIT-2 — Gatekeeper failed jobs must NOT charge the caller
# ---------------------------------------------------------------------------


class TestGatekeeperFailedJobsNoCharge:
    """A verification job that fails (Z3 returned error, invalid SMT2,
    or any exception in the verifier backend) must not charge the caller.

    Integrators submit thousands of jobs and cannot be expected to debug
    Z3 parse errors after being silently billed. CRIT-2: charge-on-submit
    must be refunded (or waived) when the job ends in a FAILED state.
    """

    async def test_failed_verification_job_refunds_charge(self, client, app):
        """Submit a job with syntactically-invalid SMT2 → the mock verifier
        logs a FAILED job → caller's wallet must be made whole.

        Uses a direct ``GatekeeperAPI.submit_verification`` + a stub
        verifier that always raises, so the test is deterministic and
        does not depend on z3-solver being installed.
        """
        from products.gatekeeper.src.models import VerificationStatus

        ctx = app.state.ctx
        # Create a pro-tier agent (submit_verification requires "pro" tier).
        await ctx.tracker.wallet.create("pro-fail-charge", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-fail-charge", tier="pro")
        key = key_info["key"]

        # Install a stub verifier that always raises so every job fails.
        class _AlwaysFailVerifier:
            async def invoke(self, job_spec):  # noqa: ARG002
                raise RuntimeError("stub: verifier unreachable")

        original_verifier = ctx.gatekeeper_api.verifier
        ctx.gatekeeper_api.verifier = _AlwaysFailVerifier()
        try:
            balance_before = float(await ctx.tracker.get_balance("pro-fail-charge"))

            resp = await client.post(
                "/v1/gatekeeper/jobs",
                json={
                    "agent_id": "pro-fail-charge",
                    "properties": [
                        {"name": "broken", "expression": "(declare-const x Int)\n(assert (> x 0))"},
                    ],
                },
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            job_id = body["job_id"]

            # The mock verifier raised → job ended up FAILED.
            job = await ctx.gatekeeper_api.storage.get_job(job_id)
            assert job is not None
            assert job.status == VerificationStatus.FAILED, (
                f"test precondition: expected FAILED job, got {job.status}"
            )

            balance_after = float(await ctx.tracker.get_balance("pro-fail-charge"))
            assert balance_after == balance_before, (
                f"CRIT-2: failed verification must not charge caller; "
                f"balance went from {balance_before} → {balance_after}"
            )
        finally:
            ctx.gatekeeper_api.verifier = original_verifier


# ---------------------------------------------------------------------------
# v1.2.2 feature — JSON policy language for Gatekeeper
# ---------------------------------------------------------------------------


class TestGatekeeperJsonPolicyLanguage:
    """Gatekeeper must accept high-level JSON policies in addition to raw
    SMT-LIB2, compiling them transparently before invoking the verifier.
    """

    async def test_submit_with_json_policy_language(self, client, app):
        """A submission with ``language='json_policy'`` is accepted and
        the property is compiled to SMT2 before the verifier runs.
        """
        import json as _json

        class _RecordingVerifier:
            def __init__(self):
                self.last_spec = None

            async def invoke(self, job_spec):
                self.last_spec = job_spec
                return {
                    "job_id": job_spec["job_id"],
                    "status": "completed",
                    "result": "satisfied",
                    "property_results": [
                        {"name": p["name"], "result": "satisfied", "model": "x=1"}
                        for p in job_spec["properties"]
                    ],
                    "proof_data": "",
                    "proof_hash": "",
                }

        ctx = app.state.ctx
        await ctx.tracker.wallet.create("policy-agent", initial_balance=500.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("policy-agent", tier="pro")
        key = key_info["key"]

        original = ctx.gatekeeper_api.verifier
        recorder = _RecordingVerifier()
        ctx.gatekeeper_api.verifier = recorder
        try:
            policy_json = _json.dumps(
                {
                    "name": "positive_balance",
                    "variables": [{"name": "balance", "type": "int"}],
                    "assertions": [{"op": ">", "args": ["balance", 0]}],
                }
            )
            resp = await client.post(
                "/v1/gatekeeper/jobs",
                json={
                    "agent_id": "policy-agent",
                    "properties": [
                        {
                            "name": "positive_balance",
                            "language": "json_policy",
                            "expression": policy_json,
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code == 201, resp.text
            # Verifier must have seen compiled SMT-LIB2, not raw JSON.
            assert recorder.last_spec is not None
            sent_expr = recorder.last_spec["properties"][0]["expression"]
            assert "declare-const balance Int" in sent_expr
            assert "(> balance 0)" in sent_expr
            assert recorder.last_spec["properties"][0]["language"] == "z3_smt2"
        finally:
            ctx.gatekeeper_api.verifier = original

    async def test_submit_with_invalid_json_policy_rejected(self, client, app):
        """Malformed JSON policy must be rejected at submission time with
        a 4xx error rather than leaking through to the verifier.
        """
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("policy-agent2", initial_balance=500.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("policy-agent2", tier="pro")
        key = key_info["key"]

        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "policy-agent2",
                "properties": [
                    {
                        "name": "bad",
                        "language": "json_policy",
                        "expression": "{not-valid-json",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# P1 indie DX — /v1/onboarding quickstart must use REST routes, not /v1/execute
# ---------------------------------------------------------------------------


class TestOnboardingQuickstartUsesRest:
    """First-time integrators land on ``/v1/onboarding``. The quickstart
    examples they see must point at the REST routes (which every other
    page of the docs documents), not at the legacy ``/v1/execute`` JSON
    envelope.
    """

    async def test_quickstart_has_no_execute_envelope(self, client):
        resp = await client.get("/v1/onboarding")
        assert resp.status_code == 200
        spec = resp.json()
        quickstart = spec.get("info", {}).get("x-onboarding", {}).get("quickstart", [])
        assert quickstart, "onboarding quickstart missing"

        combined = "\n".join(step.get("example", "") for step in quickstart)
        assert "/v1/execute" not in combined, (
            f"quickstart must not use /v1/execute; got: {combined}"
        )
        # Sanity: it should mention at least one real REST path.
        assert "/v1/billing/wallets/" in combined or "/v1/marketplace" in combined, (
            f"quickstart should reference REST routes; got: {combined}"
        )
