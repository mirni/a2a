"""Tests for subscription gateway tools (TDD — written before implementation)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_subscription_via_gateway(client, pro_api_key, app):
    """Pro agent can create a subscription."""
    ctx = app.state.ctx
    # Need a payee wallet
    await ctx.tracker.wallet.create("signal-provider", initial_balance=0.0, signup_bonus=False)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_subscription",
            "params": {
                "payer": "pro-agent",
                "payee": "signal-provider",
                "amount": 10.0,
                "interval": "daily",
                "description": "Signal feed subscription",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    result = data["result"]
    assert result["status"] == "active"
    assert result["amount"] == 10.0
    assert "id" in result


async def test_cancel_subscription_via_gateway(client, pro_api_key, app):
    """Pro agent can cancel a subscription."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("provider-b", initial_balance=0.0, signup_bonus=False)

    # Create subscription first
    sub = await ctx.payment_engine.create_subscription(
        payer="pro-agent", payee="provider-b", amount=5.0, interval="daily"
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "cancel_subscription",
            "params": {"subscription_id": sub.id, "cancelled_by": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["status"] == "cancelled"


async def test_get_subscription_via_gateway(client, pro_api_key, app):
    """Pro agent can get subscription details."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("provider-c", initial_balance=0.0, signup_bonus=False)

    sub = await ctx.payment_engine.create_subscription(
        payer="pro-agent", payee="provider-c", amount=15.0, interval="weekly"
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_subscription",
            "params": {"subscription_id": sub.id},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["id"] == sub.id
    assert result["amount"] == 15.0
    assert result["interval"] == "weekly"


async def test_list_subscriptions_via_gateway(client, pro_api_key, app):
    """Pro agent can list subscriptions."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("provider-d", initial_balance=0.0, signup_bonus=False)

    await ctx.payment_engine.create_subscription(payer="pro-agent", payee="provider-d", amount=5.0, interval="daily")
    await ctx.payment_engine.create_subscription(payer="pro-agent", payee="provider-d", amount=10.0, interval="weekly")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_subscriptions",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["subscriptions"]) == 2


async def test_reactivate_subscription_via_gateway(client, pro_api_key, app):
    """Pro agent can reactivate a suspended subscription."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("provider-e", initial_balance=0.0, signup_bonus=False)

    sub = await ctx.payment_engine.create_subscription(
        payer="pro-agent", payee="provider-e", amount=5.0, interval="daily"
    )
    # Suspend it
    await ctx.payment_engine.suspend_subscription(sub.id)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "reactivate_subscription",
            "params": {"subscription_id": sub.id},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "active"


async def test_create_subscription_requires_pro(client, api_key):
    """Free tier cannot create subscriptions."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_subscription",
            "params": {
                "payer": "test-agent",
                "payee": "someone",
                "amount": 10.0,
                "interval": "daily",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
