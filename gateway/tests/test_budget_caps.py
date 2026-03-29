"""Tests for P3-22: Spending Alerts / Budget Caps (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_set_budget_cap(client, api_key):
    """Set a daily and monthly budget cap."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "set_budget_cap",
            "params": {
                "agent_id": "test-agent",
                "daily_cap": 100.0,
                "monthly_cap": 2000.0,
                "alert_threshold": 0.8,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "test-agent"
    assert result["daily_cap"] == 100.0
    assert result["monthly_cap"] == 2000.0
    assert result["alert_threshold"] == 0.8


async def test_set_budget_cap_defaults(client, api_key):
    """Set budget cap with only agent_id uses defaults."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "set_budget_cap",
            "params": {
                "agent_id": "test-agent",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "test-agent"
    assert result["alert_threshold"] == 0.8  # default


async def test_get_budget_status_no_cap(client, api_key):
    """Get budget status when no cap is set."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_budget_status",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "test-agent"
    assert result["alert_triggered"] is False
    assert result["cap_exceeded"] is False


async def test_get_budget_status_with_spending(client, api_key, app):
    """Budget status reflects actual spending vs caps."""
    ctx = app.state.ctx

    # Set a budget cap
    await client.post(
        "/v1/execute",
        json={
            "tool": "set_budget_cap",
            "params": {
                "agent_id": "test-agent",
                "daily_cap": 10.0,
                "monthly_cap": 100.0,
                "alert_threshold": 0.5,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Record some usage (6 credits = 60% of daily cap)
    for _ in range(6):
        await ctx.tracker.storage.record_usage(agent_id="test-agent", function="some_tool", cost=1.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_budget_status",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "test-agent"
    assert result["daily_spend"] >= 6.0
    assert result["daily_cap"] == 10.0
    # 60% > 50% threshold => alert triggered
    assert result["alert_triggered"] is True
    assert result["cap_exceeded"] is False


async def test_budget_cap_exceeded(client, api_key, app):
    """When spending exceeds the cap, cap_exceeded is True."""
    ctx = app.state.ctx

    # Set a tight cap
    await client.post(
        "/v1/execute",
        json={
            "tool": "set_budget_cap",
            "params": {
                "agent_id": "test-agent",
                "daily_cap": 5.0,
                "monthly_cap": 50.0,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Record 10 credits of usage (exceeds daily cap of 5)
    for _ in range(10):
        await ctx.tracker.storage.record_usage(agent_id="test-agent", function="expensive_tool", cost=1.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_budget_status",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["cap_exceeded"] is True
    assert result["alert_triggered"] is True


async def test_set_budget_cap_missing_agent_id(client, api_key):
    """Missing agent_id should return 400."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "set_budget_cap",
            "params": {"daily_cap": 100.0},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
