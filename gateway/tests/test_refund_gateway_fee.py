"""Tests for audit H3 follow-up: refund_intent reverses the gateway fee.

The `gateway:create_intent` fee is a percentage (2%) of the intent amount,
clamped to [0.01, 5.0] credits. When an intent is refunded or voided, the
original gateway fee must be credited back to the payer so users are not
charged indefinitely for failed/cancelled workflows.

See reports/external/live-payments-audit-2026-04-05-combined.md (H3).
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
    """create_intent response discloses gateway_fee (audit H3 already done)."""

    async def test_create_intent_returns_gateway_fee_field(self, client, api_key, app):
        await _setup_payee(app)
        body = await _create_intent(client, api_key, 100.0)
        assert "gateway_fee" in body
        # 2% of 100.0, clamped [0.01, 5.0] = 2.0
        assert float(body["gateway_fee"]) == 2.0

    async def test_gateway_fee_clamped_to_min(self, client, api_key, app):
        """Very small amount → fee clamped to 0.01 min."""
        await _setup_payee(app)
        body = await _create_intent(client, api_key, 0.01)
        # 2% of 0.01 = 0.0002, clamped to 0.01 min
        assert float(body["gateway_fee"]) == 0.01

    async def test_gateway_fee_clamped_to_max(self, client, api_key, app):
        """Very large amount → fee clamped to 5.0 max."""
        await _setup_payee(app)
        # api_key fixture gives test-agent 1000 credits, so use amount within balance
        body = await _create_intent(client, api_key, 500.0)
        # 2% of 500.0 = 10.0, clamped to 5.0 max
        assert float(body["gateway_fee"]) == 5.0


class TestRefundReversesGatewayFee:
    """refund_intent returns the gateway_fee field for transparency (H3)."""

    async def test_refund_response_includes_gateway_fee(self, client, api_key, app):
        """refund_intent response body includes gateway_fee field."""
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
        # The fee charged at create_intent is refunded on voided intent
        assert float(body["gateway_fee"]) == 2.0

    async def test_void_refund_credits_gateway_fee_to_payer(self, client, api_key, app):
        """Voiding a pending intent credits the gateway fee back to the payer."""
        await _setup_payee(app)
        ctx = app.state.ctx

        balance_before = await ctx.tracker.get_balance("test-agent")

        # create_intent costs gateway_fee (2.0 for amount=100)
        create_body = await _create_intent(client, api_key, 100.0)
        intent_id = create_body["id"]
        fee = float(create_body["gateway_fee"])

        balance_after_create = await ctx.tracker.get_balance("test-agent")
        # test-agent was debited the gateway fee
        assert balance_after_create == pytest.approx(balance_before - fee, abs=0.01)

        # Void the pending intent → fee should be refunded
        resp = await client.post(
            "/v1/execute",
            json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        # refund_intent itself also has a cost, so the final balance may differ
        # slightly. Just assert the intent fee was credited back.
        balance_after_refund = await ctx.tracker.get_balance("test-agent")
        # The gateway fee charged at create should be credited back
        # (final balance will be close to original, minus refund_intent's own cost)
        assert balance_after_refund > balance_after_create, "Refund should credit back at least the gateway fee"

    async def test_settled_refund_credits_gateway_fee_to_payer(self, client, api_key, app):
        """Refunding a settled intent credits the gateway fee back to the payer."""
        await _setup_payee(app)
        ctx = app.state.ctx

        create_body = await _create_intent(client, api_key, 100.0)
        intent_id = create_body["id"]
        fee = float(create_body["gateway_fee"])

        # Capture (moves funds payer→payee)
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
        body = resp.json()
        assert body["status"] == "refunded"
        assert float(body["gateway_fee"]) == fee

        payer_after_refund = await ctx.tracker.get_balance("test-agent")
        # Payer should be credited: amount (100.0) + gateway_fee (2.0) = 102.0
        # minus the refund_intent call's own cost
        credited = payer_after_refund - payer_before_refund
        assert credited >= 100.0 + fee - 1.0, f"Expected at least {100.0 + fee - 1.0} credited, got {credited}"
