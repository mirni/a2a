"""Tests for rate policies and spend caps."""

from __future__ import annotations

import pytest
from src.policies import RateLimitExceededError, RatePolicyManager, SpendCapExceededError
from src.storage import StorageBackend


class TestPolicyManagement:
    async def test_set_and_get_policy(self, policies: RatePolicyManager):
        await policies.set_policy("agent-1", max_calls_per_min=60, max_spend_per_day=500.0)
        policy = await policies.get_policy("agent-1")
        assert policy is not None
        assert policy["max_calls_per_min"] == 60
        assert policy["max_spend_per_day"] == 500.0

    async def test_get_policy_returns_none(self, policies: RatePolicyManager):
        assert await policies.get_policy("nobody") is None

    async def test_update_policy(self, policies: RatePolicyManager):
        await policies.set_policy("agent-1", max_calls_per_min=10)
        await policies.set_policy("agent-1", max_calls_per_min=20, max_spend_per_day=100.0)
        policy = await policies.get_policy("agent-1")
        assert policy["max_calls_per_min"] == 20

    async def test_delete_policy(self, policies: RatePolicyManager):
        await policies.set_policy("agent-1", max_calls_per_min=10)
        await policies.delete_policy("agent-1")
        assert await policies.get_policy("agent-1") is None


class TestRateLimitCheck:
    async def test_no_policy_passes(self, policies: RatePolicyManager):
        # No policy = no limits
        await policies.check_rate_limit("agent-1")  # should not raise

    async def test_under_limit_passes(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_calls_per_min=10)
        # Record 5 calls
        for _ in range(5):
            await storage.record_usage("agent-1", "f", 1.0)
        await policies.check_rate_limit("agent-1")  # should not raise

    async def test_at_limit_raises(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_calls_per_min=3)
        for _ in range(3):
            await storage.record_usage("agent-1", "f", 1.0)
        with pytest.raises(RateLimitExceededError) as exc_info:
            await policies.check_rate_limit("agent-1")
        assert exc_info.value.limit_type == "calls_per_min"
        assert exc_info.value.current == 3
        assert exc_info.value.limit == 3

    async def test_null_limit_passes(self, policies: RatePolicyManager, storage: StorageBackend):
        # Policy exists but max_calls_per_min is None
        await policies.set_policy("agent-1", max_spend_per_day=100.0)
        for _ in range(100):
            await storage.record_usage("agent-1", "f", 0.0)
        await policies.check_rate_limit("agent-1")  # should not raise


class TestSpendCapCheck:
    async def test_no_policy_passes(self, policies: RatePolicyManager):
        await policies.check_spend_cap("agent-1", 1000.0)  # should not raise

    async def test_under_cap_passes(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_spend_per_day=100.0)
        await storage.record_usage("agent-1", "f", 50.0)
        await policies.check_spend_cap("agent-1", 10.0)  # 50 + 10 = 60 < 100

    async def test_exceeds_cap_raises(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_spend_per_day=100.0)
        await storage.record_usage("agent-1", "f", 90.0)
        with pytest.raises(SpendCapExceededError) as exc_info:
            await policies.check_spend_cap("agent-1", 20.0)
        assert exc_info.value.current_spend == pytest.approx(110.0)
        assert exc_info.value.cap == 100.0

    async def test_null_cap_passes(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_calls_per_min=10)
        await storage.record_usage("agent-1", "f", 9999.0)
        await policies.check_spend_cap("agent-1", 9999.0)  # should not raise


class TestCheckAll:
    async def test_check_all_passes(self, policies: RatePolicyManager):
        await policies.check_all("agent-1", cost=100.0)  # no policy = pass

    async def test_check_all_rate_limit_fails(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_calls_per_min=1)
        await storage.record_usage("agent-1", "f", 1.0)
        with pytest.raises(RateLimitExceededError):
            await policies.check_all("agent-1", cost=1.0)

    async def test_check_all_spend_cap_fails(self, policies: RatePolicyManager, storage: StorageBackend):
        await policies.set_policy("agent-1", max_spend_per_day=10.0)
        await storage.record_usage("agent-1", "f", 9.0)
        with pytest.raises(SpendCapExceededError):
            await policies.check_all("agent-1", cost=5.0)
