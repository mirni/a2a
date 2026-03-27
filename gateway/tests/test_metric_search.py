"""Tests for cross-agent metric search (TDD)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_search_agents_by_metric(client, pro_api_key, app):
    """Search for agents with Sharpe >= 2.0."""
    ctx = app.state.ctx

    # Register two agents and submit metrics
    await ctx.identity_api.register_agent("bot-alpha")
    await ctx.identity_api.register_agent("bot-beta")
    await ctx.identity_api.register_agent("bot-gamma")

    await ctx.identity_api.submit_metrics("bot-alpha", {"sharpe_30d": 2.5})
    await ctx.identity_api.submit_metrics("bot-beta", {"sharpe_30d": 1.2})
    await ctx.identity_api.submit_metrics("bot-gamma", {"sharpe_30d": 3.1})

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "search_agents_by_metrics",
            "params": {
                "metric_name": "sharpe_30d",
                "min_value": 2.0,
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    agent_ids = [a["agent_id"] for a in result["agents"]]
    assert "bot-alpha" in agent_ids
    assert "bot-gamma" in agent_ids
    assert "bot-beta" not in agent_ids


async def test_search_agents_by_max_drawdown(client, pro_api_key, app):
    """Search for agents with max_drawdown_30d <= 5.0."""
    ctx = app.state.ctx

    await ctx.identity_api.register_agent("dd-bot-a")
    await ctx.identity_api.register_agent("dd-bot-b")

    await ctx.identity_api.submit_metrics("dd-bot-a", {"max_drawdown_30d": 3.2})
    await ctx.identity_api.submit_metrics("dd-bot-b", {"max_drawdown_30d": 8.5})

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "search_agents_by_metrics",
            "params": {
                "metric_name": "max_drawdown_30d",
                "max_value": 5.0,
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    agent_ids = [a["agent_id"] for a in result["agents"]]
    assert "dd-bot-a" in agent_ids
    assert "dd-bot-b" not in agent_ids


async def test_search_agents_empty_result(client, pro_api_key, app):
    """Search returns empty when no agents match."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "search_agents_by_metrics",
            "params": {
                "metric_name": "sharpe_30d",
                "min_value": 999.0,
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["agents"] == []
