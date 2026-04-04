"""Tests for P2 #22: Leaderboard test data filtering.

Agents matching perf-*, test-*, audit-*, stress-* must be excluded.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestLeaderboardFilter:
    """Leaderboard should filter out test/perf/audit agents."""

    async def test_test_agents_excluded(self, client, api_key, app):
        """Agents with test-* prefix should not appear in leaderboard."""
        ctx = app.state.ctx
        # Create real + test agents with usage
        await ctx.tracker.wallet.create("real-agent-lb", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("real-agent-lb", "t1", 50.0)

        await ctx.tracker.wallet.create("test-bot-001", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("test-bot-001", "t1", 999.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        agent_ids = [e["agent_id"] for e in data["leaderboard"]]
        assert "test-bot-001" not in agent_ids

    async def test_perf_agents_excluded(self, client, api_key, app):
        """Agents with perf-* prefix should not appear in leaderboard."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("perf-load-test", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("perf-load-test", "t1", 800.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agent_ids = [e["agent_id"] for e in resp.json()["leaderboard"]]
        assert "perf-load-test" not in agent_ids

    async def test_audit_agents_excluded(self, client, api_key, app):
        """Agents with audit-* prefix should not appear in leaderboard."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("audit-scanner", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("audit-scanner", "t1", 700.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agent_ids = [e["agent_id"] for e in resp.json()["leaderboard"]]
        assert "audit-scanner" not in agent_ids

    async def test_stress_agents_excluded(self, client, api_key, app):
        """Agents with stress-* prefix should not appear in leaderboard."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("stress-test-1", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("stress-test-1", "t1", 600.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agent_ids = [e["agent_id"] for e in resp.json()["leaderboard"]]
        assert "stress-test-1" not in agent_ids

    async def test_real_agents_still_visible(self, client, api_key, app):
        """Normal agents should still appear in leaderboard."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("real-lb-agent", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("real-lb-agent", "t1", 42.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agent_ids = [e["agent_id"] for e in resp.json()["leaderboard"]]
        assert "real-lb-agent" in agent_ids
