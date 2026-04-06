"""Tests for P1-9: Partial capture of payment intents."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _payer_key(app, agent_id="payer-agent", balance=500.0):
    """Create wallet + API key for a payer agent."""
    ctx = app.state.ctx
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except Exception:
        pass
    key_info = await ctx.key_manager.create_key(agent_id, tier="pro")
    return key_info["key"]


async def test_partial_capture_basic(client, app):
    """Partial capture of 30 from a 100 intent returns settlement for 30."""
    ctx = app.state.ctx
    payer_key = await _payer_key(app, "payer-agent")
    await ctx.tracker.wallet.create("payee-agent", initial_balance=0.0, signup_bonus=False)

    # Create a payment intent
    intent = await ctx.payment_engine.create_intent(payer="payer-agent", payee="payee-agent", amount=100.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "partial_capture",
            "params": {"intent_id": intent.id, "amount": 30.0},
        },
        headers={"Authorization": f"Bearer {payer_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["amount"]) == 30.0
    assert body["status"] == "settled"
    assert "id" in body


async def test_partial_capture_updates_remaining(client, app):
    """After partial capture, the intent's remaining amount is reduced."""
    ctx = app.state.ctx
    payer_key = await _payer_key(app, "payer2")
    await ctx.tracker.wallet.create("payee2", initial_balance=0.0, signup_bonus=False)

    intent = await ctx.payment_engine.create_intent(payer="payer2", payee="payee2", amount=100.0)

    # Partial capture of 40
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "partial_capture",
            "params": {"intent_id": intent.id, "amount": 40.0},
        },
        headers={"Authorization": f"Bearer {payer_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["remaining_amount"] == 60.0


async def test_partial_capture_full_amount_voids_intent(client, app):
    """Capturing the full remaining amount voids the intent (nothing left)."""
    ctx = app.state.ctx
    payer_key = await _payer_key(app, "payer3")
    await ctx.tracker.wallet.create("payee3", initial_balance=0.0, signup_bonus=False)

    intent = await ctx.payment_engine.create_intent(payer="payer3", payee="payee3", amount=100.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "partial_capture",
            "params": {"intent_id": intent.id, "amount": 100.0},
        },
        headers={"Authorization": f"Bearer {payer_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["remaining_amount"] == 0.0

    # Verify the intent status is now settled/voided
    updated_intent = await ctx.payment_engine.get_intent(intent.id)
    assert updated_intent.status.value in ("settled", "voided")


async def test_partial_capture_exceeds_amount_fails(client, app):
    """Capturing more than the intent amount should fail."""
    ctx = app.state.ctx
    payer_key = await _payer_key(app, "payer4")
    await ctx.tracker.wallet.create("payee4", initial_balance=0.0, signup_bonus=False)

    intent = await ctx.payment_engine.create_intent(payer="payer4", payee="payee4", amount=50.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "partial_capture",
            "params": {"intent_id": intent.id, "amount": 75.0},
        },
        headers={"Authorization": f"Bearer {payer_key}"},
    )
    assert resp.status_code == 400


async def test_partial_capture_missing_params(client, pro_api_key):
    """Missing required parameters returns 400."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "partial_capture", "params": {"intent_id": "abc"}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"].endswith("/missing-parameter")


async def test_partial_capture_not_found(client, pro_api_key):
    """Capturing a nonexistent intent returns 404."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "partial_capture",
            "params": {"intent_id": "nonexistent", "amount": 10.0},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 404
