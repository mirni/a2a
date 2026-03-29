"""Budget caps and spending alerts.

Enforces daily/monthly spending limits and emits alert events
when spending approaches thresholds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from shared_src.pricing_config import load_pricing_config

from .storage import StorageBackend

_pricing = load_pricing_config()
_DEFAULT_ALERT_THRESHOLD = _pricing.budget.get("alert_threshold", 0.8)


class BudgetCapExceededError(Exception):
    """Raised when a charge would exceed a budget cap."""

    def __init__(self, agent_id: str, cap_type: str, current_spend: float, cap: float) -> None:
        self.agent_id = agent_id
        self.cap_type = cap_type
        self.current_spend = current_spend
        self.cap = cap
        super().__init__(f"Agent {agent_id}: {cap_type} budget cap exceeded. Spend: {current_spend}, Cap: {cap}")


@dataclass
class BudgetManager:
    """Manages budget caps and spending alerts."""

    storage: StorageBackend

    async def set_cap(
        self,
        agent_id: str,
        daily_cap: float | None = None,
        monthly_cap: float | None = None,
        alert_threshold: float = _DEFAULT_ALERT_THRESHOLD,
    ) -> None:
        """Set budget caps for an agent."""
        await self.storage.set_budget_cap(agent_id, daily_cap, monthly_cap, alert_threshold)

    async def get_cap(self, agent_id: str) -> dict[str, Any] | None:
        """Get budget cap config for an agent, or None."""
        return await self.storage.get_budget_cap(agent_id)

    async def delete_cap(self, agent_id: str) -> None:
        """Remove budget caps for an agent."""
        await self.storage.delete_budget_cap(agent_id)

    async def check_budget(self, agent_id: str, additional_cost: float = 0.0) -> None:
        """Check if a charge would exceed budget caps.

        Emits a budget.alert event if spending crosses the alert threshold.
        Raises BudgetCapExceededError if the cap would be exceeded.
        """
        cap = await self.storage.get_budget_cap(agent_id)
        if cap is None:
            return  # No cap = no limits

        now = time.time()
        threshold = cap.get("alert_threshold", _DEFAULT_ALERT_THRESHOLD)

        # Check daily cap
        if cap["daily_cap"] is not None:
            day_start = now - (now % 86400)
            daily_spend = await self.storage.sum_cost_since(agent_id, day_start)
            projected = daily_spend + additional_cost

            if projected > cap["daily_cap"]:
                raise BudgetCapExceededError(agent_id, "daily", projected, cap["daily_cap"])

            # Emit alert if crossing threshold
            if projected >= cap["daily_cap"] * threshold and daily_spend < cap["daily_cap"] * threshold:
                await self.storage.emit_event(
                    "budget.alert",
                    agent_id,
                    {
                        "cap_type": "daily",
                        "current_spend": projected,
                        "cap": cap["daily_cap"],
                        "threshold": threshold,
                    },
                )

        # Check monthly cap
        if cap["monthly_cap"] is not None:
            # Start of current month (approximate: 30-day rolling window)
            month_start = now - (30 * 86400)
            monthly_spend = await self.storage.sum_cost_since(agent_id, month_start)
            projected = monthly_spend + additional_cost

            if projected > cap["monthly_cap"]:
                raise BudgetCapExceededError(agent_id, "monthly", projected, cap["monthly_cap"])

            # Emit alert if crossing threshold
            if projected >= cap["monthly_cap"] * threshold and monthly_spend < cap["monthly_cap"] * threshold:
                await self.storage.emit_event(
                    "budget.alert",
                    agent_id,
                    {
                        "cap_type": "monthly",
                        "current_spend": projected,
                        "cap": cap["monthly_cap"],
                        "threshold": threshold,
                    },
                )
