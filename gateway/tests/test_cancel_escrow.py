"""Tests for cancel_escrow tool (P0-6)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_escrow(client, api_key, app):
    """Helper: create an escrow and return its ID."""
    # Fund both agents
    ctx = app.state.ctx
    try:
        await ctx.tracker.wallet.create("payer-agent", initial_balance=1000.0)
    except Exception:
        pass
    try:
        await ctx.tracker.wallet.create("payee-agent", initial_balance=0.0)
    except Exception:
        pass

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_escrow",
            "params": {
                "payer": "payer-agent",
                "payee": "payee-agent",
                "amount": 50.0,
                "description": "test escrow",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]["id"]


async def test_cancel_escrow_refunds_payer(client, pro_api_key, app):
    """cancel_escrow should refund the payer and return status 'refunded'."""
    escrow_id = await _create_escrow(client, pro_api_key, app)

    # Check payer balance before cancel
    ctx = app.state.ctx
    balance_before = await ctx.tracker.get_balance("payer-agent")

    resp = await client.post(
        "/v1/execute",
        json={"tool": "cancel_escrow", "params": {"escrow_id": escrow_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["result"]["id"] == escrow_id
    assert body["result"]["status"] == "refunded"

    # Payer should have been refunded
    balance_after = await ctx.tracker.get_balance("payer-agent")
    assert balance_after > balance_before


async def test_cancel_escrow_not_found(client, pro_api_key):
    """cancel_escrow with unknown ID should return 404."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "cancel_escrow", "params": {"escrow_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 404


async def test_cancel_escrow_already_settled(client, pro_api_key, app):
    """cancel_escrow on a settled escrow should return 409 (invalid state)."""
    escrow_id = await _create_escrow(client, pro_api_key, app)

    # Release the escrow first
    await client.post(
        "/v1/execute",
        json={"tool": "release_escrow", "params": {"escrow_id": escrow_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )

    # Now trying to cancel should fail
    resp = await client.post(
        "/v1/execute",
        json={"tool": "cancel_escrow", "params": {"escrow_id": escrow_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 409
