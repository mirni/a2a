"""Tests for the UsageTracker and metered decorator."""

from __future__ import annotations

import pytest
from src.policies import RateLimitExceededError, SpendCapExceededError
from src.tracker import UsageTracker, require_credits
from src.wallet import InsufficientCreditsError


class TestTrackerLifecycle:
    async def test_context_manager(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            assert tracker.storage is not None
            assert tracker.wallet is not None
            assert tracker.policies is not None
            assert tracker.events is not None

    async def test_connect_and_close(self, tmp_db):
        tracker = UsageTracker(storage=tmp_db)
        await tracker.connect()
        assert tracker.storage.db is not None
        await tracker.close()


class TestMeteredDecorator:
    async def test_basic_metering(self, tracker: UsageTracker):
        @tracker.metered(cost=2.0)
        async def my_func(agent_id, data):
            return data * 2

        result = await my_func("agent-1", 21)
        assert result == 42

        usage = await tracker.get_usage("agent-1")
        assert len(usage) == 1
        assert usage[0]["cost"] == 2.0
        assert "my_func" in usage[0]["function"]

    async def test_metering_with_kwargs(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0)
        async def my_func(agent_id, value=10):
            return value

        result = await my_func(agent_id="agent-1", value=99)
        assert result == 99

        usage = await tracker.get_usage("agent-1")
        assert len(usage) == 1

    async def test_metering_records_tokens(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0, tokens_param="tokens")
        async def my_func(agent_id, tokens=0):
            return "done"

        await my_func("agent-1", tokens=500)
        usage = await tracker.get_usage("agent-1")
        assert usage[0]["tokens"] == 500

    async def test_metering_no_agent_id_raises(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0)
        async def my_func():
            return "done"

        with pytest.raises(ValueError, match="Cannot determine agent_id"):
            await my_func()

    async def test_metering_emits_event(self, tracker: UsageTracker):
        received = []

        @tracker.events.on_event
        async def handler(event):
            received.append(event)

        @tracker.metered(cost=3.0)
        async def my_func(agent_id):
            return "ok"

        await my_func("agent-1")
        # Filter for usage events (wallet.created etc. may also be emitted)
        usage_events = [e for e in received if e["event_type"] == "usage.recorded"]
        assert len(usage_events) == 1
        assert usage_events[0]["payload"]["cost"] == 3.0


class TestMeteredWithBalance:
    async def test_require_balance_charges_wallet(self, tracker: UsageTracker):
        await tracker.wallet.create("agent-1", 100.0, signup_bonus=False)

        @tracker.metered(cost=10.0, require_balance=True)
        async def my_func(agent_id):
            return "ok"

        result = await my_func("agent-1")
        assert result == "ok"

        balance = await tracker.get_balance("agent-1")
        assert balance == 90.0

    async def test_require_balance_insufficient_raises(self, tracker: UsageTracker):
        await tracker.wallet.create("agent-1", 5.0, signup_bonus=False)

        @tracker.metered(cost=10.0, require_balance=True)
        async def my_func(agent_id):
            return "ok"

        with pytest.raises(InsufficientCreditsError):
            await my_func("agent-1")

    async def test_require_balance_no_wallet_raises(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0, require_balance=True)
        async def my_func(agent_id):
            return "ok"

        with pytest.raises(InsufficientCreditsError):
            await my_func("agent-1")


class TestMeteredWithPolicies:
    async def test_rate_limit_enforced(self, tracker: UsageTracker):
        await tracker.policies.set_policy("agent-1", max_calls_per_min=2)

        @tracker.metered(cost=1.0)
        async def my_func(agent_id):
            return "ok"

        await my_func("agent-1")
        await my_func("agent-1")

        with pytest.raises(RateLimitExceededError):
            await my_func("agent-1")

    async def test_spend_cap_enforced(self, tracker: UsageTracker):
        await tracker.policies.set_policy("agent-1", max_spend_per_day=5.0)

        @tracker.metered(cost=3.0)
        async def my_func(agent_id):
            return "ok"

        await my_func("agent-1")
        # 3.0 already spent, next call would be 3+3=6 > 5
        with pytest.raises(SpendCapExceededError):
            await my_func("agent-1")


class TestUsageAPI:
    async def test_get_usage_summary(self, tracker: UsageTracker):
        @tracker.metered(cost=2.0)
        async def my_func(agent_id):
            return "ok"

        await my_func("agent-1")
        await my_func("agent-1")

        summary = await tracker.get_usage_summary("agent-1")
        assert summary["total_calls"] == 2
        assert summary["total_cost"] == 4.0

    async def test_get_projected_cost(self, tracker: UsageTracker):
        @tracker.metered(cost=10.0)
        async def my_func(agent_id):
            return "ok"

        await my_func("agent-1")

        projection = await tracker.get_projected_cost("agent-1", hours=1.0)
        assert projection["total_cost_in_period"] == 10.0
        assert projection["total_calls_in_period"] == 1
        assert projection["rate_per_hour"] == 10.0
        assert projection["projected_24h_cost"] == 240.0


class TestUsageFunctionFilter:
    async def test_get_usage_with_function_filter(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0)
        async def tool_a(agent_id):
            return "a"

        @tracker.metered(cost=2.0)
        async def tool_b(agent_id):
            return "b"

        await tool_a("agent-1")
        await tool_a("agent-1")
        await tool_b("agent-1")

        # Filter by tool_a's qualified name
        usage_a = await tracker.get_usage("agent-1", function="tool_a")
        assert len(usage_a) == 2
        for u in usage_a:
            assert "tool_a" in u["function"]

    async def test_get_usage_without_function_filter(self, tracker: UsageTracker):
        @tracker.metered(cost=1.0)
        async def tool_a(agent_id):
            return "a"

        @tracker.metered(cost=2.0)
        async def tool_b(agent_id):
            return "b"

        await tool_a("agent-1")
        await tool_b("agent-1")

        # Without filter, should return all
        usage = await tracker.get_usage("agent-1")
        assert len(usage) == 2


class TestRequireCreditsDecorator:
    async def test_require_credits_decorator(self, tracker: UsageTracker):
        await tracker.wallet.create("agent-1", 50.0, signup_bonus=False)

        @require_credits(tracker, cost=5.0)
        async def expensive_func(agent_id):
            return "expensive result"

        result = await expensive_func("agent-1")
        assert result == "expensive result"

        balance = await tracker.get_balance("agent-1")
        assert balance == 45.0

    async def test_require_credits_insufficient(self, tracker: UsageTracker):
        await tracker.wallet.create("agent-1", 2.0, signup_bonus=False)

        @require_credits(tracker, cost=5.0)
        async def expensive_func(agent_id):
            return "expensive result"

        with pytest.raises(InsufficientCreditsError):
            await expensive_func("agent-1")
