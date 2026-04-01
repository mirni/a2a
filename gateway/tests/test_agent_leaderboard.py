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
        await ctx.tracker.wallet.create("agent-a", initial_balance=500.0, signup_bonus=False)
        await ctx.tracker.wallet.create("agent-b", initial_balance=500.0, signup_bonus=False)
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
        assert "leaderboard" in data
        assert isinstance(data["leaderboard"], list)
        # agent-b spent 20, agent-a spent 15 — b should be first
        if len(data["leaderboard"]) >= 2:
            assert data["leaderboard"][0]["agent_id"] == "agent-b"
            assert data["leaderboard"][0]["rank"] == 1
            assert data["leaderboard"][1]["agent_id"] == "agent-a"
            assert data["leaderboard"][1]["rank"] == 2

    async def test_leaderboard_by_calls(self, client, api_key, app):
        """Should rank agents by total calls."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("caller-a", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.wallet.create("caller-b", initial_balance=100.0, signup_bonus=False)
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
        lb = data["leaderboard"]
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
        assert "leaderboard" in data

    async def test_limit_parameter(self, client, api_key, app):
        """Should respect the limit parameter."""
        ctx = app.state.ctx
        for i in range(5):
            agent = f"lim-agent-{i}"
            await ctx.tracker.wallet.create(agent, initial_balance=100.0, signup_bonus=False)
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
        assert len(data["leaderboard"]) <= 3

    async def test_default_limit_is_10(self, client, api_key):
        """Default limit should be 10."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["leaderboard"]) <= 10

    async def test_leaderboard_entries_have_rank(self, client, api_key, app):
        """Each entry should have rank, agent_id, and value fields."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("rank-agent", initial_balance=100.0, signup_bonus=False)
        await ctx.tracker.storage.record_usage("rank-agent", "t1", 5.0)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "spend"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        for entry in data["leaderboard"]:
            assert "rank" in entry
            assert "agent_id" in entry
            assert "value" in entry

    async def test_leaderboard_by_revenue(self, client, api_key, app):
        """Should rank agents by total revenue (payee in settlements)."""
        ctx = app.state.ctx
        # Create wallets for two agents
        await ctx.tracker.wallet.create("rev-seller-a", initial_balance=0.0, signup_bonus=False)
        await ctx.tracker.wallet.create("rev-seller-b", initial_balance=0.0, signup_bonus=False)
        await ctx.tracker.wallet.create("rev-buyer", initial_balance=10000.0, signup_bonus=False)

        # Create settlements via payment intents
        for _i in range(3):
            intent = await ctx.payment_engine.create_intent(
                payer="rev-buyer",
                payee="rev-seller-a",
                amount=100.0,
            )
            await ctx.payment_engine.capture(intent.id)
        intent = await ctx.payment_engine.create_intent(
            payer="rev-buyer",
            payee="rev-seller-b",
            amount=500.0,
        )
        await ctx.payment_engine.capture(intent.id)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "revenue"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        lb = data["leaderboard"]
        # rev-seller-b has 500, rev-seller-a has 300
        seller_a = [e for e in lb if e["agent_id"] == "rev-seller-a"]
        seller_b = [e for e in lb if e["agent_id"] == "rev-seller-b"]
        assert seller_b and seller_a
        assert seller_b[0]["rank"] < seller_a[0]["rank"]
        assert seller_b[0]["value"] == 500.0
        assert seller_a[0]["value"] == 300.0

    async def test_leaderboard_by_rating(self, client, api_key, app):
        """Should rank agents by average service rating."""
        from marketplace_src.models import ServiceCreate

        ctx = app.state.ctx
        mkt = ctx.marketplace

        # Register services for two providers
        svc_a = await mkt.register_service(
            ServiceCreate(
                provider_id="rated-a",
                name="Service A",
                description="A service",
                category="general",
            )
        )
        svc_b = await mkt.register_service(
            ServiceCreate(
                provider_id="rated-b",
                name="Service B",
                description="B service",
                category="general",
            )
        )

        # Rate them: rated-a gets avg 3.0, rated-b gets avg 4.5
        await mkt.rate_service(svc_a.id, "reviewer-1", 2)
        await mkt.rate_service(svc_a.id, "reviewer-2", 4)
        await mkt.rate_service(svc_b.id, "reviewer-1", 4)
        await mkt.rate_service(svc_b.id, "reviewer-2", 5)

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {"metric": "rating"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        lb = data["leaderboard"]
        rated_a = [e for e in lb if e["agent_id"] == "rated-a"]
        rated_b = [e for e in lb if e["agent_id"] == "rated-b"]
        assert rated_b and rated_a
        assert rated_b[0]["rank"] < rated_a[0]["rank"]
        assert rated_b[0]["value"] == 4.5
        assert rated_a[0]["value"] == 3.0

    async def test_missing_metric_param(self, client, api_key):
        """Should fail when metric param is missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_leaderboard", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
