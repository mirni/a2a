"""Regression tests for multi-persona audit v1.2.2 findings.

Source: ``reports/external/v1.2.2/multi-persona-audit-v1.2.2-2026-04-10.md``

Covers every CRIT/HIGH finding that the engineering team can reproduce
against the in-process test client:

* **CRIT-1** — Gatekeeper Z3 verifier wiring. The v1.2.2 sandbox shipped
  with ``VERIFIER_AUTH_MODE`` unset, so every job ended up FAILED in
  <14 ms. Covered by ``gateway/tests/test_gatekeeper_verifier.py``
  (lifespan defensive default).
* **CRIT-2** — Failed verification job response echoed ``cost:"6"`` even
  though the wallet was never debited. The response must report
  ``cost:"0"`` + ``billed_cost:"0"`` for failed/timeout jobs and emit
  the full ``billed_cost`` for completed jobs.
* **CRIT-3/4** — ``/v1/infra/keys`` was per-agent scoped but the
  response omitted the ``agent_id`` field, so auditors could not verify
  ownership. The response must include ``agent_id`` and ``owner:"self"``
  on every row, and isolation across agents must be explicitly tested.
* **CRIT-NEW** — An ``enterprise``-tier key must not be able to read
  ``/v1/infra/audit-log`` (that tool is admin-only).
* **HIGH-5** — ``CREDITS→ETH`` round-trip destroyed value because the
  default rate table only seeded ``ETH→CREDITS``. Both directions must
  be seeded and the 18-decimal working precision must preserve ≥ 99 %
  of value on round-trips.
* **HIGH-7** — Key rotation has no grace window and no confirmation
  header, so two consecutive audit cycles accidentally rotated the
  production PRO key during schema probing.
* **HIGH-2** — Refund response transparently disclosed that the 2 %
  gateway fee was retained, but never documented *why*. The response
  must now include a ``fee_policy`` field referencing the ADR so
  integrators can cite a stable URL in their own reconciliation docs.
* **HIGH-8** — API key provisioning does not auto-create an identity
  record, so ``/v1/identity/agents/{id}/reputation`` 404s until the
  caller registers themselves.

Each test is standalone — no shared state — so they can also serve as
permanent BOLA/regression fixtures.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# CRIT-2 — Failed Gatekeeper jobs must report cost:"0"
# ---------------------------------------------------------------------------


class TestGatekeeperCostZeroOnFailure:
    """A failed verification job must report ``cost:"0"`` + ``billed_cost:"0"``.

    v1.2.2 correctly waived the wallet debit via ``tc.cost = 0.0`` but the
    response body still echoed the catalog list price, so audit personas
    concluded (incorrectly) that they were being charged for failed jobs.
    The response contract is now:

        * ``cost`` — amount actually debited from the caller's wallet
        * ``billed_cost`` — same value, explicit alias for clarity

    Successful jobs emit both as the real catalog price; failed jobs
    emit ``"0"`` for both.
    """

    async def test_failed_submit_reports_cost_zero(self, client, app):
        """Submit → verifier raises → response has cost:"0" billed_cost:"0"."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-cost-zero", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-cost-zero", tier="pro")
        key = key_info["key"]

        class _AlwaysFailVerifier:
            async def invoke(self, job_spec):  # noqa: ARG002
                raise RuntimeError("stub: verifier unreachable")

        original = ctx.gatekeeper_api.verifier
        ctx.gatekeeper_api.verifier = _AlwaysFailVerifier()
        try:
            resp = await client.post(
                "/v1/gatekeeper/jobs",
                json={
                    "agent_id": "pro-cost-zero",
                    "properties": [
                        {
                            "name": "p",
                            "expression": "(declare-const x Int)\n(assert (> x 0))",
                        },
                    ],
                },
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] in {"failed", "timeout"}
            assert body["cost"] == "0", f"cost must be zeroed on failure: {body}"
            assert body["billed_cost"] == "0", f"billed_cost field must be explicitly zero: {body}"
        finally:
            ctx.gatekeeper_api.verifier = original

    async def test_failed_status_reports_cost_zero(self, client, app):
        """GET /v1/gatekeeper/jobs/{id} on a failed job also reports zeros."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-cost-status", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-cost-status", tier="pro")
        key = key_info["key"]

        class _AlwaysFailVerifier:
            async def invoke(self, job_spec):  # noqa: ARG002
                raise RuntimeError("stub: verifier unreachable")

        original = ctx.gatekeeper_api.verifier
        ctx.gatekeeper_api.verifier = _AlwaysFailVerifier()
        try:
            submit = await client.post(
                "/v1/gatekeeper/jobs",
                json={
                    "agent_id": "pro-cost-status",
                    "properties": [
                        {
                            "name": "p",
                            "expression": "(declare-const x Int)\n(assert (> x 0))",
                        },
                    ],
                },
                headers={"Authorization": f"Bearer {key}"},
            )
            assert submit.status_code == 201, submit.text
            job_id = submit.json()["job_id"]

            status = await client.get(
                f"/v1/gatekeeper/jobs/{job_id}",
                headers={"Authorization": f"Bearer {key}"},
            )
            assert status.status_code == 200
            data = status.json()
            assert data["status"] == "failed"
            assert data["cost"] == "0"
            assert data["billed_cost"] == "0"
        finally:
            ctx.gatekeeper_api.verifier = original


# ---------------------------------------------------------------------------
# CRIT-3/4 — /v1/infra/keys must include agent_id + owner
# ---------------------------------------------------------------------------


class TestInfraKeysOwnershipAttribution:
    """Each row of ``GET /v1/infra/keys`` must carry ``agent_id`` and
    ``owner:"self"`` so callers can verify ownership from the response
    alone. The auditors in v1.2.2 flagged a "fleet leak" based on the
    absence of this field — the endpoint was actually correctly scoped
    at the SQL layer, but the response was ambiguous.
    """

    async def test_response_rows_include_agent_id_and_owner_self(self, client, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("alice-owned-keys", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("alice-owned-keys", tier="free")
        key = key_info["key"]

        resp = await client.get("/v1/infra/keys", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200
        body = resp.json()
        assert "keys" in body
        assert len(body["keys"]) >= 1
        for row in body["keys"]:
            assert row["agent_id"] == "alice-owned-keys", f"every row must report its owning agent_id: {row}"
            assert row["owner"] == "self", f"every row must be marked owner:self: {row}"

    async def test_cross_agent_isolation(self, client, app):
        """Two free-tier agents can only see their own keys."""
        ctx = app.state.ctx
        for aid in ("alice-iso", "bob-iso"):
            await ctx.tracker.wallet.create(aid, initial_balance=100.0, signup_bonus=False)
        alice_key_info = await ctx.key_manager.create_key("alice-iso", tier="free")
        bob_key_info = await ctx.key_manager.create_key("bob-iso", tier="free")

        alice_resp = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {alice_key_info['key']}"},
        )
        bob_resp = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {bob_key_info['key']}"},
        )
        assert alice_resp.status_code == 200
        assert bob_resp.status_code == 200

        alice_ids = {row["agent_id"] for row in alice_resp.json()["keys"]}
        bob_ids = {row["agent_id"] for row in bob_resp.json()["keys"]}
        assert alice_ids == {"alice-iso"}, f"alice leaked: {alice_ids}"
        assert bob_ids == {"bob-iso"}, f"bob leaked: {bob_ids}"


# ---------------------------------------------------------------------------
# CRIT-NEW — Enterprise tier is not admin
# ---------------------------------------------------------------------------


class TestEnterpriseIsNotAdmin:
    """``enterprise`` tier must not grant access to admin-only tools.

    The v1.2.2 redteam persona observed ``200 OK`` on
    ``GET /v1/infra/audit-log`` with an ENT-tier key. Investigation
    showed the sandbox fixture was seeded with ``tier='admin'`` — this
    test pins the correct behavior regardless of fixture drift.
    """

    async def test_enterprise_cannot_read_global_audit_log(self, client, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("ent-not-admin", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("ent-not-admin", tier="enterprise")
        key = key_info["key"]

        resp = await client.get(
            "/v1/infra/audit-log",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403, (
            f"enterprise tier must NOT reach /v1/infra/audit-log, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# HIGH-5 — CREDITS ↔ crypto round-trip must preserve value
# ---------------------------------------------------------------------------


class TestCreditsCryptoRoundTrip:
    """Default rate table must seed ``CREDITS→{BTC,ETH}`` in both
    directions so users do not destroy their balances on round-trip
    conversions.
    """

    async def _make_key(self, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("fx-agent", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("fx-agent", tier="free")
        return key_info["key"]

    async def test_credits_to_eth_rate_nonzero(self, client, app):
        key = await self._make_key(app)
        resp = await client.get(
            "/v1/billing/exchange-rates?from_currency=CREDITS&to_currency=ETH",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rate = Decimal(str(body["rate"]))
        assert rate > 0, f"CREDITS→ETH rate must be non-zero, got {rate}"

    async def test_credits_to_btc_rate_nonzero(self, client, app):
        key = await self._make_key(app)
        resp = await client.get(
            "/v1/billing/exchange-rates?from_currency=CREDITS&to_currency=BTC",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        rate = Decimal(str(body["rate"]))
        assert rate > 0, f"CREDITS→BTC rate must be non-zero, got {rate}"

    async def test_credits_to_eth_roundtrip_preserves_value(self, client, app):
        """100 CREDITS → ETH → CREDITS must preserve ≥ 99 % of value."""
        from billing_src.exchange import ExchangeRateService
        from billing_src.models import Currency

        ctx = app.state.ctx
        svc = ExchangeRateService(storage=ctx.tracker.storage)
        await svc.initialize_default_rates()

        original = Decimal("100")
        eth = await svc.convert(original, Currency.CREDITS, Currency.ETH)
        assert eth.amount > 0, f"100 CREDITS must convert to non-zero ETH, got {eth.amount}"
        back = await svc.convert(eth.amount, Currency.ETH, Currency.CREDITS)
        loss = abs(original - back.amount) / original
        assert loss < Decimal("0.01"), (
            f"round-trip lost {loss:.4%} of value (100 CREDITS → {eth.amount} ETH → {back.amount} CREDITS)"
        )


# ---------------------------------------------------------------------------
# HIGH-7 — Key rotation needs a confirmation header + grace window
# ---------------------------------------------------------------------------


class TestKeyRotationSafety:
    """Rotating a key without an explicit confirmation header must fail.

    The v1.2.2 audit accidentally rotated the production PRO key
    *twice* during schema probing. The endpoint was too reachable.
    """

    async def test_rotate_without_confirmation_header_returns_428(self, client, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-rotate-safe", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-rotate-safe", tier="pro")
        key = key_info["key"]

        resp = await client.post(
            "/v1/infra/keys/rotate",
            json={"current_key": key},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 428, (
            f"rotate without X-Rotate-Confirmation must be 428, got {resp.status_code}: {resp.text}"
        )

    async def test_rotate_with_confirmation_header_succeeds(self, client, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-rotate-confirm", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-rotate-confirm", tier="pro")
        key = key_info["key"]

        resp = await client.post(
            "/v1/infra/keys/rotate",
            json={"current_key": key},
            headers={
                "Authorization": f"Bearer {key}",
                "X-Rotate-Confirmation": "confirm",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "new_key" in body or "key" in body

    async def test_old_key_remains_valid_during_grace_window(self, client, app):
        """After rotate, the old key must still authenticate for grace_seconds."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-grace", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("pro-grace", tier="pro")
        old_key = key_info["key"]

        rotate = await client.post(
            "/v1/infra/keys/rotate",
            json={"current_key": old_key},
            headers={
                "Authorization": f"Bearer {old_key}",
                "X-Rotate-Confirmation": "confirm",
            },
        )
        assert rotate.status_code == 200, rotate.text

        # Immediately after rotation the old key still authenticates
        health = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert health.status_code == 200, (
            f"old key must remain valid during grace window, got {health.status_code}: {health.text}"
        )


# ---------------------------------------------------------------------------
# HIGH-2 — Refund response must cite the fee policy ADR
# ---------------------------------------------------------------------------


class TestRefundFeePolicyDisclosure:
    """HIGH-2 (v1.2.2): refund response must include a ``fee_policy``
    field that names the policy (``retain_gateway_fee``) and links to
    the ADR so integrators can reference a stable URL in their
    reconciliation docs. The ``fee_refunded`` / ``fee_retained`` fields
    remain in place for backwards compatibility.
    """

    async def test_refund_response_includes_fee_policy(self, client, app):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("refund-policy-payer", initial_balance=1000.0, signup_bonus=False)
        await ctx.tracker.wallet.create("refund-policy-payee", initial_balance=0.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("refund-policy-payer", tier="pro")
        key = key_info["key"]

        create = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "refund-policy-payer",
                "payee": "refund-policy-payee",
                "amount": "50.00",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert create.status_code == 201, create.text
        intent_id = create.json()["id"]

        cap = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            json={},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert cap.status_code == 200, cap.text

        ref = await client.post(
            f"/v1/payments/intents/{intent_id}/refund",
            json={},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert ref.status_code == 200, ref.text
        body = ref.json()

        assert "fee_policy" in body, f"HIGH-2: refund response must include fee_policy; got {list(body.keys())}"
        policy = body["fee_policy"]
        assert isinstance(policy, dict), f"fee_policy must be an object: {policy}"
        assert policy.get("name") == "retain_gateway_fee", f"fee_policy.name must be 'retain_gateway_fee': {policy}"
        assert "adr" in policy and policy["adr"].startswith("ADR-"), f"fee_policy.adr must reference the ADR: {policy}"
        assert policy.get("url"), f"fee_policy.url must be set: {policy}"

        # Backwards compatibility: legacy fields remain
        assert body.get("fee_refunded") is False
        assert body.get("fee_retained") is not None


# ---------------------------------------------------------------------------
# HIGH-8 — Identity auto-binds on key provisioning
# ---------------------------------------------------------------------------


class TestIdentityAutoBind:
    """``POST /v1/infra/keys`` must idempotently create the agent's
    identity record so the caller can immediately read
    ``/v1/identity/agents/{id}/reputation`` without a second registration.
    """

    async def test_new_key_can_read_reputation_immediately(self, client, app):
        ctx = app.state.ctx
        # Seed a pro key so we can call provision on another agent via the
        # REST API. Alternatively create the key directly and call the
        # reputation endpoint.
        await ctx.tracker.wallet.create("auto-bind-owner", initial_balance=100.0, signup_bonus=False)
        key_info = await ctx.key_manager.create_key("auto-bind-owner", tier="pro")
        key = key_info["key"]

        rep = await client.get(
            "/v1/identity/agents/auto-bind-owner/reputation",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert rep.status_code == 200, (
            f"newly-provisioned agent must have an identity record, got {rep.status_code}: {rep.text}"
        )
