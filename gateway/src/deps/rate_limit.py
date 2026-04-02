"""Rate limiting dependency."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger("a2a.deps.rate_limit")


def build_rate_limit_headers(
    limit: int,
    rate_count: int,
    window_seconds: float = 3600.0,
) -> dict[str, str]:
    """Build X-RateLimit-* headers."""
    remaining = max(0, limit - rate_count)
    reset = max(1, math.ceil(window_seconds - (time.time() % window_seconds)))
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }


async def check_rate_limits(
    ctx: Any,
    agent_id: str,
    tier: str,
    tool_name: str,
    tool_def: dict[str, Any],
) -> int:
    """Check global and per-tool rate limits.

    Records the rate event BEFORE checking counts so that concurrent
    requests each see an up-to-date count (increment-then-check).

    Returns the current rate_count for header generation.
    Raises RateLimitError if limits are exceeded.
    """
    from gateway.src.authorization import ADMIN_TIER

    if tier == ADMIN_TIER:
        return 0

    from paywall_src.tiers import get_tier_config, tier_has_access

    required_tier = tool_def.get("tier_required", "free")
    if not tier_has_access(tier, required_tier):
        raise TierError(tier, tool_name, required_tier)

    tier_config = get_tier_config(tier)
    window_key = "gateway"

    try:
        # Record rate event FIRST (increment-then-check) so concurrent
        # requests each see an up-to-date count.
        await ctx.paywall_storage.record_rate_event(agent_id, window_key, tool_name)

        rate_count = await ctx.paywall_storage.get_sliding_window_count(agent_id, window_key, window_seconds=3600.0)
        if rate_count >= tier_config.rate_limit_per_hour:
            burst_count = await ctx.paywall_storage.get_burst_count(agent_id, window_key, burst_window_seconds=60.0)
            burst_limit = tier_config.rate_limit_per_hour // 60 + tier_config.burst_allowance
            if burst_count >= burst_limit:
                raise RateLimitError(rate_count, tier_config.rate_limit_per_hour)

        tool_rate_limit = tool_def.get("rate_limit_per_hour")
        if tool_rate_limit is not None:
            tool_rate_count = await ctx.paywall_storage.get_tool_rate_count(agent_id, tool_name, window_seconds=3600.0)
            if tool_rate_count >= tool_rate_limit:
                raise RateLimitError(tool_rate_count, tool_rate_limit, tool_name=tool_name)
    except (RuntimeError, OSError):
        logger.error("Rate limit check failed for agent %s", agent_id, exc_info=True)
        raise ServiceError("Rate limit service unavailable") from None

    return rate_count


class TierError(Exception):
    """Raised when tier is insufficient."""

    def __init__(self, tier: str, tool_name: str, required_tier: str) -> None:
        super().__init__(f"Tier '{tier}' cannot access tool '{tool_name}' (requires '{required_tier}')")
        self.tier = tier
        self.tool_name = tool_name
        self.required_tier = required_tier


class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, count: int, limit: int, tool_name: str | None = None) -> None:
        if tool_name:
            msg = f"Per-tool rate limit exceeded for '{tool_name}': {count}/{limit} per hour"
        else:
            msg = f"Rate limit exceeded: {count}/{limit} per hour"
        super().__init__(msg)
        self.count = count
        self.limit = limit


class ServiceError(Exception):
    """Raised when a backend service is unavailable."""
