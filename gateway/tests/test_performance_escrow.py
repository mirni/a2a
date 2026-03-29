"""Tests for performance-gated escrow (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_performance_escrow(client, pro_api_key, app):
    """Create an escrow that auto-releases when metric threshold is met."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("signal-buyer", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("signal-seller", initial_balance=0.0, signup_bonus=False)
    buyer_key = await ctx.key_manager.create_key("signal-buyer", tier="pro")

    # Register the seller identity
    await ctx.identity_api.register_agent("signal-seller")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_performance_escrow",
            "params": {
                "payer": "signal-buyer",
                "payee": "signal-seller",
                "amount": 100.0,
                "metric_name": "sharpe_30d",
                "threshold": 2.0,
                "description": "Pay if Sharpe >= 2.0",
            },
        },
        headers={"Authorization": f"Bearer {buyer_key['key']}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "held"
    assert result["metric_name"] == "sharpe_30d"
    assert result["threshold"] == 2.0


async def test_check_performance_escrow_releases(client, pro_api_key, app):
    """Escrow auto-releases when metric exceeds threshold."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("buyer-a", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("seller-a", initial_balance=0.0, signup_bonus=False)
    buyer_key = await ctx.key_manager.create_key("buyer-a", tier="pro")

    await ctx.identity_api.register_agent("seller-a")

    # Create performance escrow
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_performance_escrow",
            "params": {
                "payer": "buyer-a",
                "payee": "seller-a",
                "amount": 50.0,
                "metric_name": "sharpe_30d",
                "threshold": 1.5,
            },
        },
        headers={"Authorization": f"Bearer {buyer_key['key']}"},
    )
    escrow_id = resp.json()["result"]["escrow_id"]

    # Seller submits metrics that meet threshold
    await ctx.identity_api.submit_metrics("seller-a", {"sharpe_30d": 2.0})

    # Check escrow → should auto-release
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "check_performance_escrow",
            "params": {"escrow_id": escrow_id},
        },
        headers={"Authorization": f"Bearer {buyer_key['key']}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["released"] is True

    # Verify seller received funds
    seller_balance = await ctx.tracker.wallet.get_balance("seller-a")
    assert seller_balance == 50.0


async def test_check_performance_escrow_not_met(client, pro_api_key, app):
    """Escrow stays held when metric below threshold."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("buyer-b", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("seller-b", initial_balance=0.0, signup_bonus=False)
    buyer_key = await ctx.key_manager.create_key("buyer-b", tier="pro")

    await ctx.identity_api.register_agent("seller-b")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_performance_escrow",
            "params": {
                "payer": "buyer-b",
                "payee": "seller-b",
                "amount": 50.0,
                "metric_name": "sharpe_30d",
                "threshold": 3.0,
            },
        },
        headers={"Authorization": f"Bearer {buyer_key['key']}"},
    )
    escrow_id = resp.json()["result"]["escrow_id"]

    # Seller submits metrics BELOW threshold
    await ctx.identity_api.submit_metrics("seller-b", {"sharpe_30d": 1.5})

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "check_performance_escrow",
            "params": {"escrow_id": escrow_id},
        },
        headers={"Authorization": f"Bearer {buyer_key['key']}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["released"] is False
