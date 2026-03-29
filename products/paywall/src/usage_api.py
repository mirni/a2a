"""Usage dashboard API: summary, history, projected cost.

Delegates to the billing layer's UsageTracker for actual usage data,
and augments with tier-specific context from the paywall storage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .keys import KeyManager
from .storage import PaywallStorage
from .tiers import get_tier_config

# The tracker is typed as Any to avoid cross-package import issues.
# At runtime it's a billing layer UsageTracker instance.


@dataclass
class UsageAPI:
    """High-level usage dashboard operations."""

    tracker: Any  # UsageTracker instance from billing layer
    key_manager: KeyManager
    storage: PaywallStorage

    async def get_summary(self, agent_id: str, hours: float = 24.0) -> dict[str, Any]:
        """Get usage summary for the current period.

        Returns call count, total cost, tier info, and rate limit status.
        """
        since = time.time() - (hours * 3600)
        summary = await self.tracker.get_usage_summary(agent_id, since)

        # Get agent tier from their keys
        keys = await self.storage.get_keys_for_agent(agent_id)
        active_keys = [k for k in keys if not k["revoked"]]
        tier_name = active_keys[0]["tier"] if active_keys else "free"
        tier_config = get_tier_config(tier_name)

        return {
            "agent_id": agent_id,
            "tier": tier_name,
            "period_hours": hours,
            "total_calls": summary["total_calls"],
            "total_cost": summary["total_cost"],
            "rate_limit_per_hour": tier_config.rate_limit_per_hour,
            "audit_log_retention_days": tier_config.audit_log_retention_days,
        }

    async def get_history(
        self,
        agent_id: str,
        since: float | None = None,
        until: float | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get usage history for an agent."""
        return await self.tracker.get_usage(agent_id, since, until, limit)

    async def get_projected_cost(self, agent_id: str, hours: float = 24.0) -> dict[str, Any]:
        """Get projected cost based on recent usage patterns."""
        projection = await self.tracker.get_projected_cost(agent_id, hours)

        # Augment with tier info
        keys = await self.storage.get_keys_for_agent(agent_id)
        active_keys = [k for k in keys if not k["revoked"]]
        tier_name = active_keys[0]["tier"] if active_keys else "free"
        tier_config = get_tier_config(tier_name)

        projection["tier"] = tier_name
        projection["cost_per_call"] = tier_config.cost_per_call

        return projection
