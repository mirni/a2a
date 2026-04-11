"""Regression tests for multi-persona audit v1.2.3 findings.

Source: ``reports/external/v1.2.3/multi-persona-audit-v1.2.3-2026-04-10.md``

Covers the findings that the engineering team can reproduce against
the in-process test client and that belong to gateway code (not the
external SDK, staging infra, or the Lambda verifier):

* **NEW-CRIT-1** — ``X-API-Key`` header as alternate auth must be
  configurable, and the extracted key must be stripped of surrounding
  whitespace so trailing-space / tab tricks cannot smuggle keys past
  upstream filters.
* **NEW-CRIT-2** — ``Authorization: Bearer <key>`` must ignore trailing
  whitespace in the extracted value (``Bearer abc `` → ``"abc"``).
* **NEW-CRIT-3** — ``GET /v1%2Finfra%2Fkeys`` and other URL-encoded-slash
  forms must be rejected with a 400 so attackers cannot slip past
  WAF/proxy rules that match on literal ``/v1/infra/``.
* **CRIT-4** — ``X-Forwarded-For`` spoofing: the gateway must only
  trust XFF when the immediate peer is in ``A2A_TRUSTED_PROXIES``.
  By default (no trusted proxies configured) XFF must be ignored for
  rate-limiting and all log lines.
* **HIGH-2** — Full refund of 50.00 must return 50.00, not 49.00.
  The 2% gateway fee must be waived / reversed on a full refund.
* **MED-7** — ``/v1/infra/databases/{db}/backup`` and ``/integrity``
  must not return absolute filesystem paths (``/var/lib/a2a/...``).
* **MED-8** — ``POST /v1/infra/keys/rotate`` must not report
  ``"revoked": true`` while the old key still authenticates. The
  response shape must honestly reflect the 300 s grace window.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# NEW-CRIT-1 / NEW-CRIT-2 — Authorization header hardening
# ---------------------------------------------------------------------------


class TestAuthorizationHeaderHardening:
    """Bearer token extraction must strip whitespace; key smuggling via
    trailing whitespace/tab characters must not succeed.
    """

    async def test_bearer_with_trailing_space_still_authenticates(self, client, api_key):
        """``Bearer <key> `` (trailing space) must authenticate cleanly.

        Without the fix the extracted key is ``"<key> "`` (with the
        trailing space) which either rejects a valid key (if the key
        store hashes exact strings) or — worse — authenticates a key
        the operator never issued because WAF rules matching the
        exact key string fail to match the padded value.
        """
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer {api_key} "},
        )
        assert resp.status_code == 200, resp.text

    async def test_bearer_with_trailing_tab_still_authenticates(self, client, api_key):
        """``Bearer <key>\\t`` must authenticate — the tab is stripped."""
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer {api_key}\t"},
        )
        assert resp.status_code == 200, resp.text

    async def test_bearer_with_leading_whitespace_after_scheme_authenticates(self, client, api_key):
        """``Bearer   <key>`` (multiple spaces after scheme) is valid."""
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer   {api_key}"},
        )
        assert resp.status_code == 200, resp.text

    async def test_bearer_empty_after_scheme_is_rejected(self, client):
        """``Bearer`` (no key) must not authenticate."""
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": "Bearer "},
        )
        assert resp.status_code == 401


class TestXApiKeyHeaderExtraction:
    """The ``X-API-Key`` header is documented (HIGH-1) but the extracted
    value must be stripped of whitespace for the same smuggling
    reasons as the Authorization header.
    """

    async def test_x_api_key_trailing_whitespace_authenticates(self, client, api_key):
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"X-API-Key": f"{api_key}\t "},
        )
        assert resp.status_code == 200, resp.text

    async def test_empty_x_api_key_is_rejected(self, client):
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"X-API-Key": "   "},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# NEW-CRIT-3 — URL-encoded path separator rejection
# ---------------------------------------------------------------------------


class TestUrlEncodedPathSeparatorRejection:
    """``%2F`` and ``%5C`` inside a ``/v1/`` path must be rejected with
    400 so upstream WAF/proxy rules that match on literal substrings
    cannot be bypassed by encoding the separators.
    """

    async def test_percent_encoded_slash_in_path_is_rejected(self, client, api_key):
        """``GET /v1%2Finfra%2Fkeys`` → 400."""
        resp = await client.get(
            "/v1%2Finfra%2Fkeys",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert "encoded" in resp.text.lower() or "invalid" in resp.text.lower()

    async def test_mixed_case_percent_encoded_slash_is_rejected(self, client, api_key):
        """``GET /v1%2fbilling%2Fwallets%2ftest-agent%2fbalance`` → 400."""
        resp = await client.get(
            "/v1%2fbilling%2Fwallets%2ftest-agent%2fbalance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400

    async def test_percent_encoded_backslash_rejected(self, client, api_key):
        """``%5C`` (backslash) in path is also rejected."""
        resp = await client.get(
            "/v1%5Cinfra%5Ckeys",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# CRIT-4 — X-Forwarded-For spoofing without a trusted proxy
# ---------------------------------------------------------------------------


class TestXForwardedForTrust:
    """Without ``A2A_TRUSTED_PROXIES`` set, the gateway must ignore
    forwarded-for headers entirely and use the ASGI client tuple.
    """

    async def test_spoofed_xff_is_ignored_for_rate_limiting(self, client, monkeypatch):
        """Two requests from the same peer with different spoofed XFF
        values must share the same rate-limit bucket (because XFF is
        ignored, both map to the ASGI client).

        We verify this by reading the middleware's stored ``client_ip``
        from the response header ``X-Client-IP-Resolved`` (a debug
        header added by the hardened middleware).
        """
        # Make sure no trusted proxies are configured.
        monkeypatch.delenv("A2A_TRUSTED_PROXIES", raising=False)

        resp1 = await client.get(
            "/v1/health",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        resp2 = await client.get(
            "/v1/health",
            headers={"X-Forwarded-For": "9.9.9.9"},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Both must resolve to the same client IP (the ASGI peer) —
        # not the spoofed XFF value.
        ip1 = resp1.headers.get("x-client-ip-resolved")
        ip2 = resp2.headers.get("x-client-ip-resolved")
        assert ip1 is not None, "hardened middleware must emit X-Client-IP-Resolved"
        assert ip1 == ip2
        assert ip1 not in {"1.2.3.4", "9.9.9.9"}


# ---------------------------------------------------------------------------
# HIGH-2 — Full refund must not retain gateway fee
# ---------------------------------------------------------------------------


class TestFullRefundReturnsFullAmount:
    """Refunding an intent for the exact captured amount must return
    100% of the customer's money. Gateway fees are only earned on
    settled transactions; a full reversal must reverse the fee too.
    """

    async def _create_funded_pair(self, app, payer, payee, payer_balance=200.0, payee_balance=0.0):
        ctx = app.state.ctx
        await ctx.tracker.wallet.create(payer, initial_balance=payer_balance, signup_bonus=False)
        await ctx.tracker.wallet.create(payee, initial_balance=payee_balance, signup_bonus=False)
        payer_key = (await ctx.key_manager.create_key(payer, tier="pro"))["key"]
        return payer_key

    async def test_full_refund_returns_full_amount(self, client, app):
        payer_key = await self._create_funded_pair(app, "refund-payer", "refund-payee")
        ctx = app.state.ctx

        initial_balance = Decimal(str(await ctx.tracker.wallet.get_balance("refund-payer")))

        # Create + capture an intent for 50.00
        create = await client.post(
            "/v1/payments/intents",
            headers={"Authorization": f"Bearer {payer_key}"},
            json={
                "payer": "refund-payer",
                "payee": "refund-payee",
                "amount": "50.00",
                "currency": "CREDITS",
                "description": "audit HIGH-2 regression",
            },
        )
        assert create.status_code in (200, 201), create.text
        created_body = create.json()
        intent_id = created_body.get("intent_id") or created_body["id"]

        capture = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
            json={},
        )
        assert capture.status_code in (200, 201), capture.text

        # Full refund — body omits ``amount`` so the engine refunds everything.
        refund = await client.post(
            f"/v1/payments/intents/{intent_id}/refund",
            headers={"Authorization": f"Bearer {payer_key}"},
            json={"reason": "audit regression"},
        )
        assert refund.status_code in (200, 201), refund.text
        body = refund.json()
        refunded = Decimal(str(body.get("amount") or body.get("refunded_amount") or "0"))
        # HIGH-2: response must cite the full 50.00, not 49.00.
        assert refunded == Decimal("50.00"), (
            f"HIGH-2: full refund must cite 50.00 credits, returned {refunded}. Full body: {body!r}"
        )

        # HIGH-2 (the real check): wallet balance must be made whole.
        # The payer started with ``initial_balance``; after a full refund
        # of a fully-settled intent, the payer wallet must match the
        # starting balance — no fee retained.
        final_balance = Decimal(str(await ctx.tracker.wallet.get_balance("refund-payer")))
        assert final_balance == initial_balance, (
            f"HIGH-2: full refund must return the gateway fee to the payer. "
            f"initial={initial_balance} final={final_balance} "
            f"delta={final_balance - initial_balance} (expected 0). "
            f"Refund response: {body!r}"
        )

        # And the rotation response must reflect the new policy contract:
        assert body.get("fee_refunded") is True, f"HIGH-2: full refund must set fee_refunded=True; body={body!r}"
        assert Decimal(str(body.get("fee_retained", "0"))) == Decimal("0.00"), (
            f"HIGH-2: full refund must set fee_retained=0.00; body={body!r}"
        )


# ---------------------------------------------------------------------------
# MED-8 — Key rotation must not lie about revocation state
# ---------------------------------------------------------------------------


class TestRotationStateContract:
    """The rotation response must either (a) truthfully report that
    the old key is still valid for the grace window, or (b) make the
    old key stop working immediately.

    Current behaviour: response says ``"revoked": true`` but the old
    key keeps authenticating for 300 s. That is a contract lie.
    """

    async def test_rotate_response_does_not_claim_revoked_while_grace_active(self, client, admin_api_key):
        # v1.2.4 audit P0-1: rotate_key is now admin-only.
        resp = await client.post(
            "/v1/infra/keys/rotate",
            headers={
                "Authorization": f"Bearer {admin_api_key}",
                "X-Rotate-Confirmation": "confirm",
            },
            json={"current_key": admin_api_key},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()

        # Grace window contract:
        #   - ``grace_expires_at`` (or ``grace_period_seconds``) must be present
        #   - ``revoked`` must reflect the *current* state: False while the
        #     grace window is active, True once it expires.
        assert "grace_expires_at" in body or "grace_period_seconds" in body, (
            f"MED-8: rotation response must disclose grace window; body={body!r}"
        )
        # The old key must still authenticate during the grace window.
        verify = await client.get(
            "/v1/billing/wallets/admin-agent/balance",
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert verify.status_code == 200, "MED-8: old key must still authenticate during 300s grace window"
        # Therefore ``revoked`` must be False right now.
        assert body.get("revoked") is False, (
            f"MED-8: rotation body claims revoked=True while old key still authenticates; body={body!r}"
        )


# ---------------------------------------------------------------------------
# MED-7 — Filesystem path leakage
# ---------------------------------------------------------------------------


class TestFilesystemPathLeak:
    """Backup and integrity endpoints must not leak absolute filesystem
    paths to the caller. Only opaque ids / basenames.
    """

    async def test_backup_response_has_no_absolute_path(self, client, admin_api_key):
        resp = await client.post(
            "/v1/infra/databases/billing/backup",
            headers={"Authorization": f"Bearer {admin_api_key}"},
            json={"encrypt": False},
        )
        assert resp.status_code in (200, 201), resp.text
        text = resp.text
        assert "/var/lib/" not in text, f"MED-7: absolute path in backup response: {text}"
        assert "/workdir/" not in text, f"MED-7: absolute path in backup response: {text}"
        assert "/tmp/" not in text, f"MED-7: absolute path in backup response: {text}"

    async def test_integrity_response_has_no_absolute_path(self, client, admin_api_key):
        resp = await client.get(
            "/v1/infra/databases/billing/integrity",
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200, resp.text
        text = resp.text
        assert "/var/lib/" not in text
        assert "/workdir/" not in text
        assert "/tmp/" not in text
