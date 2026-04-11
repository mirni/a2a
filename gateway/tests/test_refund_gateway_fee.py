"""Tests for refund_intent gateway fee behavior.

The `gateway:create_intent` fee is a percentage (2%) of the intent amount,
clamped to [0.01, 5.0] credits.

v1.2.4 (audit v1.2.3 HIGH-2) updated policy: the gateway fee charged at
``create_intent`` time **is refunded** on a full refund / void. A full
refund must return the customer whole. Response still exposes
``gateway_fee`` for transparency, now with ``fee_refunded: True`` and
``fee_retained: "0.00"``. See ADR-012 (supersedes ADR-011).

Earlier policy (v1.0.7 H-REF / v1.2.2 retain_gateway_fee) is kept only
as a note — the tests below pin the new contract.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _setup_payee(app):
    ctx = app.state.ctx
    try:
        await ctx.tracker.wallet.create("rgf-payee", initial_balance=500.0, signup_bonus=False)
    except Exception:
        pass


async def _create_intent(client, api_key, amount):
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "rgf-payee",
                "amount": amount,
                "description": "fee-refund test",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


class TestGatewayFeeInCreateResponse:
    """create_intent response discloses gateway_fee."""

    async def test_create_intent_returns_gateway_fee_field(self, client, api_key, app):
        await _setup_payee(app)
        body = await _create_intent(client, api_key, 100.0)
        assert "gateway_fee" in body
        # 2% of 100.0, clamped [0.01, 5.0] = 2.0
        assert float(body["gateway_fee"]) == 2.0

    async def test_gateway_fee_clamped_to_min(self, client, api_key, app):
        """Very small amount -> fee clamped to 0.01 min."""
        await _setup_payee(app)
        body = await _create_intent(client, api_key, 0.01)
        # 2% of 0.01 = 0.0002, clamped to 0.01 min
        assert float(body["gateway_fee"]) == 0.01

    async def test_gateway_fee_clamped_to_max(self, client, api_key, app):
        """Very large amount -> fee clamped to 5.0 max."""
        await _setup_payee(app)
        body = await _create_intent(client, api_key, 500.0)
        # 2% of 500.0 = 10.0, clamped to 5.0 max
        assert float(body["gateway_fee"]) == 5.0


class TestRefundCreditsGatewayFee:
    """v1.2.4 (audit v1.2.3 HIGH-2): full refund restores the intent
    amount AND credits the gateway fee back. A full refund returns the
    customer whole — the gateway fee is reversed alongside the principal.
    """

    async def test_refund_response_includes_gateway_fee_field(self, client, api_key, app):
        """refund_intent response still includes gateway_fee for transparency."""
        await _setup_payee(app)
        create_body = await _create_intent(client, api_key, 100.0)
        intent_id = create_body["id"]

        resp = await client.post(
            "/v1/execute",
            json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "gateway_fee" in body
        assert float(body["gateway_fee"]) == 2.0
        # v1.2.4: full refund credits the fee back.
        assert body.get("fee_refunded") is True
        assert float(body.get("fee_retained", "0")) == 0.0

    async def test_void_credits_gateway_fee(self, client, api_key, app):
        """Voiding a pending intent credits the gateway fee back (v1.2.4)."""
        await _setup_payee(app)
        ctx = app.state.ctx

        create_body = await _create_intent(client, api_key, 100.0)
        intent_id = create_body["id"]
        gateway_fee = float(create_body["gateway_fee"])

        balance_after_create = await ctx.tracker.get_balance("test-agent")

        # Void the pending intent
        resp = await client.post(
            "/v1/execute",
            json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "voided"

        balance_after_void = await ctx.tracker.get_balance("test-agent")
        # Balance must INCREASE by gateway_fee (minus any refund_intent
        # tool-call cost, which is normally zero for the public tool).
        delta = balance_after_void - balance_after_create
        assert gateway_fee - 0.5 <= delta <= gateway_fee + 0.01, (
            f"void should credit gateway_fee={gateway_fee} back, delta={delta}"
        )

    async def test_settled_refund_restores_intent_amount_and_fee(self, client, api_key, app):
        """Refunding a settled intent restores intent amount + gateway fee."""
        await _setup_payee(app)
        ctx = app.state.ctx

        create_body = await _create_intent(client, api_key, 50.0)
        intent_id = create_body["id"]
        gateway_fee = float(create_body["gateway_fee"])  # 2% of 50 clamped to [0.01,5] = 1.0

        # Capture
        capture_resp = await client.post(
            "/v1/execute",
            json={"tool": "capture_intent", "params": {"intent_id": intent_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert capture_resp.status_code == 200

        payer_before_refund = await ctx.tracker.get_balance("test-agent")

        # Refund
        resp = await client.post(
            "/v1/execute",
            json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"

        payer_after_refund = await ctx.tracker.get_balance("test-agent")
        credited = payer_after_refund - payer_before_refund
        expected = 50.0 + gateway_fee
        assert expected - 0.5 <= credited <= expected + 0.01, (
            f"Expected ~{expected} credited (50 + {gateway_fee} fee), got {credited}"
        )
