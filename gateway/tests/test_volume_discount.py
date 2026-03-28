"""Tests for P3-18: Volume Discount Pricing (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_volume_discount_zero_history(client, api_key, app):
    """Agent with no history gets 0% discount."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {
                "agent_id": "test-agent",
                "tool_name": "get_balance",
                "quantity": 10,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "test-agent"
    assert result["tool_name"] == "get_balance"
    assert result["historical_calls"] == 0
    assert result["discount_pct"] == 0
    assert result["unit_price"] >= 0


async def test_volume_discount_tier_5pct(client, api_key, app):
    """Agent with 100-499 historical calls gets 5% discount."""
    ctx = app.state.ctx
    # Record 150 usage records for test-agent on get_balance
    for _ in range(150):
        await ctx.tracker.storage.record_usage(
            agent_id="test-agent", function="get_balance", cost=0.0
        )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {
                "agent_id": "test-agent",
                "tool_name": "get_balance",
                "quantity": 10,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["historical_calls"] == 150
    assert result["discount_pct"] == 5


async def test_volume_discount_tier_10pct(client, api_key, app):
    """Agent with 500-999 historical calls gets 10% discount."""
    ctx = app.state.ctx
    for _ in range(600):
        await ctx.tracker.storage.record_usage(
            agent_id="test-agent", function="search_services", cost=1.0
        )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {
                "agent_id": "test-agent",
                "tool_name": "search_services",
                "quantity": 50,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["historical_calls"] == 600
    assert result["discount_pct"] == 10


async def test_volume_discount_tier_15pct(client, api_key, app):
    """Agent with 1000+ historical calls gets 15% discount."""
    ctx = app.state.ctx
    for _ in range(1050):
        await ctx.tracker.storage.record_usage(
            agent_id="test-agent", function="create_intent", cost=2.0
        )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {
                "agent_id": "test-agent",
                "tool_name": "create_intent",
                "quantity": 100,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["historical_calls"] == 1050
    assert result["discount_pct"] == 15


async def test_volume_discount_discounted_price(client, api_key, app):
    """Discounted price should be unit_price * (1 - discount_pct/100)."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {
                "agent_id": "test-agent",
                "tool_name": "get_balance",
                "quantity": 5,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    expected_discounted = result["unit_price"] * (1 - result["discount_pct"] / 100)
    assert abs(result["discounted_price"] - expected_discounted) < 0.001


async def test_volume_discount_missing_params(client, api_key):
    """Missing required params should return 400."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_volume_discount",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
