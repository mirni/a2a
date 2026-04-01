"""Tests for P3-19: Cost Estimation Calculator (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_estimate_cost_basic(client, api_key):
    """Estimate cost of N calls without agent_id (no discount)."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "estimate_cost",
            "params": {
                "tool_name": "get_balance",
                "quantity": 100,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["tool_name"] == "get_balance"
    assert result["quantity"] == 100
    assert "unit_price" in result
    assert "total_cost" in result
    assert result["discount_pct"] == 0
    # total_cost = unit_price * quantity * (1 - discount/100)
    expected_total = result["unit_price"] * result["quantity"]
    assert abs(result["total_cost"] - expected_total) < 0.001


async def test_estimate_cost_with_agent_discount(client, api_key, app):
    """Estimate cost with agent_id applies volume discount."""
    ctx = app.state.ctx
    # Generate 200 calls to qualify for 5% discount
    for _ in range(200):
        await ctx.tracker.storage.record_usage(agent_id="test-agent", function="search_services", cost=1.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "estimate_cost",
            "params": {
                "tool_name": "search_services",
                "quantity": 50,
                "agent_id": "test-agent",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["discount_pct"] == 5
    expected_total = result["unit_price"] * result["quantity"] * (1 - 5 / 100)
    assert abs(result["total_cost"] - expected_total) < 0.01


async def test_estimate_cost_unknown_tool(client, api_key):
    """Estimating cost for unknown tool returns 404 ToolNotFoundError."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "estimate_cost",
            "params": {
                "tool_name": "nonexistent_tool",
                "quantity": 10,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["type"].endswith("/not-found")


async def test_estimate_cost_missing_params(client, api_key):
    """Missing required params should return 400."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "estimate_cost",
            "params": {"quantity": 10},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
