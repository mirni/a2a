"""Tests for refund_intent gateway fee behavior.

The `gateway:create_intent` fee is a percentage (2%) of the intent amount,
clamped to [0.01, 5.0] credits.  This fee is a **non-refundable** one-time
service charge.  When an intent is refunded or voided, only the intent amount
is returned — the gateway fee is NOT credited back.

See reports/external/audit-v1.0.7 (H-REF): refund must not double-credit the
gateway fee, which was causing balance drift (15.3 vs 15.0).
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


class TestRefundDoesNotCreditGatewayFee:
    """H-REF: refund restores only the intent amount. Gateway fee is non-refundable."""

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

    async def test_void_does_not_credit_gateway_fee(self, client, api_key, app):
        """Voiding a pending intent does NOT credit the gateway fee back."""
        await _setup_payee(app)
        ctx = app.state.ctx

        create_body = await _create_intent(client, api_key, 100.0)
        intent_id = create_body["id"]

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
        # Balance should NOT increase — the gateway fee is non-refundable.
        # It may decrease slightly due to the refund_intent tool call cost.
        assert balance_after_void <= balance_after_create

    async def test_settled_refund_restores_only_intent_amount(self, client, api_key, app):
        """Refunding a settled intent restores exactly the intent amount, not the fee."""
        await _setup_payee(app)
        ctx = app.state.ctx

        create_body = await _create_intent(client, api_key, 50.0)
        intent_id = create_body["id"]

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
        # Credited = intent amount (50.0) minus refund_intent's own tool call cost
        credited = payer_after_refund - payer_before_refund
        # Should be close to 50.0 (the intent amount), NOT 50.0 + 1.0 (with fee)
        assert 49.0 <= credited <= 50.01, f"Expected ~50.0 credited, got {credited}"
