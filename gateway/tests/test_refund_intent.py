"""Tests for refund_intent tool (P0-7)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _setup_agents(app):
    """Helper: create wallets for payee (payer is test-agent from fixture)."""
    ctx = app.state.ctx
    try:
        await ctx.tracker.wallet.create("ri-payee", initial_balance=500.0, signup_bonus=False)
    except Exception:
        pass


async def _create_intent(client, api_key):
    """Helper: create a payment intent and return its ID.

    Uses test-agent as payer (matches api_key fixture).
    """
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "ri-payee",
                "amount": 100.0,
                "description": "test intent for refund",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def test_refund_pending_intent_voids_it(client, api_key, app):
    """refund_intent on a pending intent should void it."""
    await _setup_agents(app)
    intent_id = await _create_intent(client, api_key)

    resp = await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "voided"
    assert body["id"] == intent_id


async def test_refund_settled_intent_creates_reverse_transfer(client, api_key, app):
    """refund_intent on a settled intent should create a reverse transfer."""
    await _setup_agents(app)
    ctx = app.state.ctx

    intent_id = await _create_intent(client, api_key)

    # Capture the intent (moves funds from payer to payee)
    capture_resp = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert capture_resp.status_code == 200

    # Record balances before refund
    payee_before = await ctx.tracker.get_balance("ri-payee")
    payer_before = await ctx.tracker.get_balance("test-agent")

    # Refund the settled intent
    resp = await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refunded"
    assert float(body["amount"]) == 100.0

    # Payee should have been debited and payer credited
    # Audit H3: refund also restores the create_intent gateway fee (2% of 100.0 = 2.0)
    payee_after = await ctx.tracker.get_balance("ri-payee")
    payer_after = await ctx.tracker.get_balance("test-agent")
    assert payer_after == payer_before + 100.0 + 2.0
    assert payee_after == payee_before - 100.0


async def test_refund_intent_not_found(client, api_key, app):
    """refund_intent with unknown ID should return 404."""
    await _setup_agents(app)
    resp = await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_refund_voided_intent_fails(client, api_key, app):
    """refund_intent on a voided intent should return 409."""
    await _setup_agents(app)
    intent_id = await _create_intent(client, api_key)

    # Void the intent first
    await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Try to refund again
    resp = await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 409
