"""Rate policies: configurable per-agent rate limits and spend caps."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .storage import StorageBackend


class RateLimitExceededError(Exception):
    """Raised when an agent exceeds their rate limit."""

    def __init__(self, agent_id: str, limit_type: str, current: float, limit: float) -> None:
        self.agent_id = agent_id
        self.limit_type = limit_type
        self.current = current
        self.limit = limit
        super().__init__(f"Agent {agent_id}: {limit_type} exceeded. Current: {current}, Limit: {limit}")


class SpendCapExceededError(Exception):
    """Raised when an agent exceeds their daily spend cap."""

    def __init__(self, agent_id: str, current_spend: float, cap: float) -> None:
        self.agent_id = agent_id
        self.current_spend = current_spend
        self.cap = cap
        super().__init__(f"Agent {agent_id}: daily spend cap exceeded. Current spend: {current_spend}, Cap: {cap}")


@dataclass
class RatePolicyManager:
    """Manages per-agent rate limits and spend caps."""

    storage: StorageBackend

    async def set_policy(
        self,
        agent_id: str,
        max_calls_per_min: int | None = None,
        max_spend_per_day: float | None = None,
    ) -> None:
        """Set or update rate policy for an agent."""
        await self.storage.set_rate_policy(agent_id, max_calls_per_min, max_spend_per_day)
        await self.storage.emit_event(
            "policy.updated",
            agent_id,
            {
                "max_calls_per_min": max_calls_per_min,
                "max_spend_per_day": max_spend_per_day,
            },
        )

    async def get_policy(self, agent_id: str) -> dict[str, Any] | None:
        """Get rate policy for an agent. Returns None if no policy set."""
        return await self.storage.get_rate_policy(agent_id)

    async def delete_policy(self, agent_id: str) -> None:
        """Remove rate policy for an agent."""
        await self.storage.delete_rate_policy(agent_id)

    async def check_rate_limit(self, agent_id: str) -> None:
        """Check if agent is within rate limits. Raises RateLimitExceededError if not."""
        policy = await self.storage.get_rate_policy(agent_id)
        if policy is None:
            return  # No policy = no limits

        if policy["max_calls_per_min"] is not None:
            since = time.time() - 60.0
            call_count = await self.storage.count_calls_since(agent_id, since)
            if call_count >= policy["max_calls_per_min"]:
                raise RateLimitExceededError(agent_id, "calls_per_min", call_count, policy["max_calls_per_min"])

    async def check_spend_cap(self, agent_id: str, additional_cost: float = 0.0) -> None:
        """Check if agent is within daily spend cap. Raises SpendCapExceededError if not."""
        policy = await self.storage.get_rate_policy(agent_id)
        if policy is None:
            return  # No policy = no cap

        if policy["max_spend_per_day"] is not None:
            # Start of current day (UTC midnight)
            now = time.time()
            day_start = now - (now % 86400)
            current_spend = await self.storage.sum_cost_since(agent_id, day_start)
            if current_spend + additional_cost > policy["max_spend_per_day"]:
                raise SpendCapExceededError(agent_id, current_spend + additional_cost, policy["max_spend_per_day"])

    async def check_all(self, agent_id: str, cost: float = 0.0) -> None:
        """Run all policy checks (rate limit + spend cap)."""
        await self.check_rate_limit(agent_id)
        await self.check_spend_cap(agent_id, cost)
