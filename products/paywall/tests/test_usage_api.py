"""Tests for Usage Dashboard API."""

from __future__ import annotations

import time

from src.keys import KeyManager
from src.usage_api import UsageAPI


class TestUsageSummary:
    async def test_summary_empty(self, usage_api: UsageAPI, key_manager: KeyManager):
        """Summary for agent with no usage should return zeros."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        summary = await usage_api.get_summary("agent-1")
        assert summary["agent_id"] == "agent-1"
        assert summary["tier"] == "pro"
        assert summary["total_calls"] == 0
        assert summary["total_cost"] == 0
        assert summary["rate_limit_per_hour"] == 10_000

    async def test_summary_with_usage(self, usage_api: UsageAPI, key_manager: KeyManager, tracker):
        """Summary should reflect recorded usage."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        # Record some usage directly in the billing tracker
        await tracker._storage.record_usage(agent_id="agent-1", function="test_fn", cost=5.0)
        await tracker._storage.record_usage(agent_id="agent-1", function="test_fn", cost=3.0)

        summary = await usage_api.get_summary("agent-1", hours=1.0)
        assert summary["total_calls"] == 2
        assert summary["total_cost"] == 8.0

    async def test_summary_free_tier(self, usage_api: UsageAPI, key_manager: KeyManager):
        """Free tier summary should show free-tier limits."""
        await key_manager.create_key(agent_id="agent-1", tier="free")

        summary = await usage_api.get_summary("agent-1")
        assert summary["tier"] == "free"
        assert summary["rate_limit_per_hour"] == 100
        assert summary["audit_log_retention_days"] is None

    async def test_summary_defaults_to_free_without_keys(self, usage_api: UsageAPI):
        """Agent with no keys defaults to 'free' tier in summary."""
        summary = await usage_api.get_summary("unknown-agent")
        assert summary["tier"] == "free"


class TestUsageHistory:
    async def test_history_empty(self, usage_api: UsageAPI):
        history = await usage_api.get_history("agent-1")
        assert history == []

    async def test_history_with_records(self, usage_api: UsageAPI, tracker):
        await tracker._storage.record_usage(agent_id="agent-1", function="fn1", cost=1.0)
        await tracker._storage.record_usage(agent_id="agent-1", function="fn2", cost=2.0)

        history = await usage_api.get_history("agent-1")
        assert len(history) == 2

    async def test_history_with_time_filter(self, usage_api: UsageAPI, tracker):
        await tracker._storage.record_usage(agent_id="agent-1", function="old_fn", cost=1.0)
        now = time.time()
        await tracker._storage.record_usage(agent_id="agent-1", function="new_fn", cost=2.0)

        history = await usage_api.get_history("agent-1", since=now - 0.01)
        assert len(history) >= 1
        functions = [h["function"] for h in history]
        assert "new_fn" in functions

    async def test_history_limit(self, usage_api: UsageAPI, tracker):
        for i in range(10):
            await tracker._storage.record_usage(agent_id="agent-1", function=f"fn{i}", cost=1.0)

        history = await usage_api.get_history("agent-1", limit=5)
        assert len(history) == 5


class TestProjectedCost:
    async def test_projected_no_usage(self, usage_api: UsageAPI, key_manager: KeyManager):
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        projection = await usage_api.get_projected_cost("agent-1")
        assert projection["projected_24h_cost"] == 0
        assert projection["tier"] == "pro"
        assert projection["cost_per_call"] == 0

    async def test_projected_with_usage(self, usage_api: UsageAPI, key_manager: KeyManager, tracker):
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        # Record usage (will count as recent usage for projection)
        for _ in range(10):
            await tracker._storage.record_usage(agent_id="agent-1", function="fn", cost=1.0)

        projection = await usage_api.get_projected_cost("agent-1", hours=1.0)
        # 10 credits in 1 hour -> rate 10/hr -> 240/day projected
        assert projection["rate_per_hour"] == 10.0
        assert projection["projected_24h_cost"] == 240.0

    async def test_projected_free_tier(self, usage_api: UsageAPI, key_manager: KeyManager):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        projection = await usage_api.get_projected_cost("agent-1")
        assert projection["tier"] == "free"
        assert projection["cost_per_call"] == 0.001
