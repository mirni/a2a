"""Billing dependency: cost calculation, balance checks, usage recording."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2a.deps.billing")


def calculate_tool_cost(pricing: dict[str, Any], params: dict[str, Any]) -> float:
    """Calculate the cost of a tool call based on the pricing model.

    Supports two pricing models:
    - "percentage": fee = clamp(amount * percentage / 100, min_fee, max_fee)
    - flat (default): fee = pricing["per_call"]
    """
    from gateway.src.tool_errors import NegativeCostError

    model = pricing.get("model")
    if model == "percentage":
        try:
            # lint-no-float-money: allow (pricing-config boundary, v1.2.9 ratchet)
            amount = float(params.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0
        pct = float(pricing.get("percentage", 0))
        # lint-no-float-money: allow (pricing-config boundary, v1.2.9 ratchet)
        min_fee = float(pricing.get("min_fee", 0))
        # lint-no-float-money: allow (pricing-config boundary, v1.2.9 ratchet)
        max_fee = float(pricing.get("max_fee", float("inf")))
        raw_fee = amount * pct / 100.0
        cost = max(min_fee, min(max_fee, raw_fee))
        if cost < 0:
            raise NegativeCostError(f"Negative cost calculated: {cost}")
        return cost
    return max(0.0, float(pricing.get("per_call", 0.0)))


async def record_usage_and_charge(
    ctx: Any,
    agent_id: str,
    tool_name: str,
    cost: float,
    idempotency_key: str | None,
    correlation_id: str,
) -> None:
    """Record usage and charge the agent's wallet.

    Note: rate events are recorded pre-execution in check_rate_limits()
    to prevent concurrent requests from bypassing the limit.
    """
    try:
        await ctx.tracker.storage.record_usage(
            agent_id=agent_id,
            function=tool_name,
            cost=cost,
            idempotency_key=idempotency_key,
        )
        if cost > 0:
            await ctx.tracker.wallet.charge(agent_id, cost, description=f"gateway:{tool_name}")
    except (RuntimeError, OSError):
        logger.warning(
            "Usage recording failed for agent %s, tool %s",
            agent_id,
            tool_name,
            exc_info=True,
        )


class BalanceError(Exception):
    """Raised when balance is insufficient."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
