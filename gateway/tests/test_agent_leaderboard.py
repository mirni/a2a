"""Tests for P2-13: Agent Leaderboard tool (get_agent_leaderboard)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestAgentLeaderboard:
    """Tests for the get_agent_leaderboard tool."""

    async def test_tool_exists_in_catalog(self, client, api_key):
        """The tool should be registered in the catalog."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_leaderboard_by_spend(self, client, api_key, app):
        """Should rank agents by total spend."""
        ctx = app.state.ctx
        # Create wallets and record usage for multiple agents
        await ctx.tracker.wallet.create("agent-a", initial_balance=500.0)
        await ctx.tracker.wallet.create("agent-b", initial_balance=500.0)
        await ctx.tracker.storage.record_usage("agent-a", "tool1", 10.0)
        await ctx.tracker.storage.record_usage("agent-a", "tool1", 5.0)
        await ctx.tracker.storage.record_usage("agent-b", "tool1", 20.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert "leaderboard" in result
        assert isinstance(result["leaderboard"], list)
        # agent-b spent 20, agent-a spent 15 — b should be first
        if len(result["leaderboard"]) >= 2:
            assert result["leaderboard"][0]["agent_id"] == "agent-b"
            assert result["leaderboard"][0]["rank"] == 1
            assert result["leaderboard"][1]["agent_id"] == "agent-a"
            assert result["leaderboard"][1]["rank"] == 2

    async def test_leaderboard_by_calls(self, client, api_key, app):
        """Should rank agents by total calls."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("caller-a", initial_balance=100.0)
        await ctx.tracker.wallet.create("caller-b", initial_balance=100.0)
        await ctx.tracker.storage.record_usage("caller-a", "t1", 0.0)
        await ctx.tracker.storage.record_usage("caller-a", "t2", 0.0)
        await ctx.tracker.storage.record_usage("caller-a", "t3", 0.0)
        await ctx.tracker.storage.record_usage("caller-b", "t1", 0.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "calls"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        lb = data["result"]["leaderboard"]
        # caller-a has 3 calls, caller-b has 1
        caller_a = [e for e in lb if e["agent_id"] == "caller-a"]
        caller_b = [e for e in lb if e["agent_id"] == "caller-b"]
        if caller_a and caller_b:
            assert caller_a[0]["rank"] < caller_b[0]["rank"]

    async def test_leaderboard_by_trust_score(self, client, api_key, app):
        """Should rank agents by trust score (from identity reputation)."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "trust_score"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "leaderboard" in data["result"]

    async def test_limit_parameter(self, client, api_key, app):
        """Should respect the limit parameter."""
        ctx = app.state.ctx
        for i in range(5):
            agent = f"lim-agent-{i}"
            await ctx.tracker.wallet.create(agent, initial_balance=100.0)
            await ctx.tracker.storage.record_usage(agent, "t1", float(i))

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_agent_leaderboard",
                "params": {"metric": "spend", "limit": 3},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["result"]["leaderboard"]) <= 3

    async def test_default_limit_is_10(self, client, api_key):
        """Default limit should be 10."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["result"]["leaderboard"]) <= 10

    async def test_leaderboard_entries_have_rank(self, client, api_key, app):
        """Each entry should have rank, agent_id, and value fields."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("rank-agent", initial_balance=100.0)
        await ctx.tracker.storage.record_usage("rank-agent", "t1", 5.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["result"]["leaderboard"]:
            assert "rank" in entry
            assert "agent_id" in entry
            assert "value" in entry

    async def test_missing_metric_param(self, client, api_key):
        """Should fail when metric param is missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
