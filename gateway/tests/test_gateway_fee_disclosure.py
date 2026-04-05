"""Tests for H3: gateway fees must be disclosed in create_intent response.

Audit H3: the 2% gateway fee on create_intent was charged but not documented
in the response body. Users creating intents for tiny amounts may pay more
in gateway fees than the intent's value. Fix: return `gateway_fee` field.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _ensure_wallet(ctx, agent_id: str, balance: float = 500.0) -> None:
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except Exception:
        pass


async def test_create_intent_response_includes_gateway_fee(client, api_key, app):
    """Response must include `gateway_fee` field showing the fee charged."""
    await _ensure_wallet(app.state.ctx, "fee-payee", 0.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "fee-payee",
                "amount": 100.0,
                "description": "fee-disclosure test",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert "gateway_fee" in body
    # 2% of 100 = 2.0
    assert float(body["gateway_fee"]) == 2.0


async def test_create_intent_fee_respects_min_fee_clamp(client, api_key, app):
    """Tiny intents are clamped to min_fee (0.01)."""
    await _ensure_wallet(app.state.ctx, "fee-payee-2", 0.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "fee-payee-2",
                "amount": 0.1,  # 2% = 0.002, but min_fee = 0.01
                "description": "min-fee clamp",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert float(body["gateway_fee"]) == 0.01


async def test_create_intent_fee_respects_max_fee_clamp(client, api_key, app):
    """Large intents are clamped to max_fee (5.0)."""
    await _ensure_wallet(app.state.ctx, "fee-payee-3", 0.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "fee-payee-3",
                "amount": 10000.0,  # 2% = 200, but max_fee = 5.0
                "description": "max-fee clamp",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    assert float(body["gateway_fee"]) == 5.0
