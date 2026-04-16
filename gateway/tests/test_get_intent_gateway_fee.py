"""Tests for gateway_fee disclosure in GET /v1/payments/intents/{id}.

v1.4.7 audit: gateway_fee is present in POST response but MISSING from
GET response.  The fee is deterministic (recomputed from amount) so
it should be included in both endpoints for reconciliation.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _ensure_wallet(ctx, agent_id: str, balance: float = 500.0) -> None:
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except Exception:
        pass


async def test_get_intent_includes_gateway_fee(client, api_key, app):
    """GET /v1/payments/intents/{id} must include gateway_fee field."""
    await _ensure_wallet(app.state.ctx, "get-fee-payee", 0.0)

    # Create an intent first
    create_resp = await client.post(
        "/v1/payments/intents",
        json={
            "payer": "test-agent",
            "payee": "get-fee-payee",
            "amount": "100.00",
            "description": "get-fee test",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert create_resp.status_code == 201, create_resp.text
    intent_id = create_resp.json()["id"]
    create_fee = create_resp.json()["gateway_fee"]

    # GET the same intent
    get_resp = await client.get(
        f"/v1/payments/intents/{intent_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()

    # gateway_fee must be present and match the POST value
    assert "gateway_fee" in body, f"gateway_fee missing from GET response: {body}"
    assert body["gateway_fee"] == create_fee
