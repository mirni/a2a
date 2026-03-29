"""Tier definitions: free, pro, enterprise with rate limits and features."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TierName(StrEnum):
    """Supported subscription tiers."""

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class TierConfig:
    """Configuration for a single tier."""

    name: TierName
    rate_limit_per_hour: int
    cost_per_call: float
    audit_log_retention_days: int | None  # None = no retention
    support_level: str
    burst_allowance: int = 10

    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit expressed per minute (for billing layer compatibility)."""
        return max(1, self.rate_limit_per_hour // 60)


# ---------------------------------------------------------------------------
# Tier registry
# ---------------------------------------------------------------------------

TIER_CONFIGS: dict[TierName, TierConfig] = {
    TierName.FREE: TierConfig(
        name=TierName.FREE,
        rate_limit_per_hour=100,
        cost_per_call=0,
        audit_log_retention_days=None,
        support_level="none",
        burst_allowance=10,
    ),
    TierName.STARTER: TierConfig(
        name=TierName.STARTER,
        rate_limit_per_hour=1_000,
        cost_per_call=0,
        audit_log_retention_days=7,
        support_level="community",
        burst_allowance=25,
    ),
    TierName.PRO: TierConfig(
        name=TierName.PRO,
        rate_limit_per_hour=10_000,
        cost_per_call=0,
        audit_log_retention_days=30,
        support_level="email",
        burst_allowance=100,
    ),
    TierName.ENTERPRISE: TierConfig(
        name=TierName.ENTERPRISE,
        rate_limit_per_hour=100_000,
        cost_per_call=0,
        audit_log_retention_days=90,
        support_level="priority",
        burst_allowance=1000,
    ),
}


def get_tier_config(tier: str | TierName) -> TierConfig:
    """Look up tier configuration by name. Raises ValueError for unknown tiers."""
    if isinstance(tier, str):
        try:
            tier = TierName(tier)
        except ValueError:
            raise ValueError(f"Unknown tier '{tier}'. Valid tiers: {[t.value for t in TierName]}") from None
    config = TIER_CONFIGS.get(tier)
    if config is None:
        raise ValueError(f"No configuration for tier '{tier}'")
    return config


# Tier ordering for access checks: higher index = higher tier
_TIER_ORDER = {TierName.FREE: 0, TierName.STARTER: 1, TierName.PRO: 2, TierName.ENTERPRISE: 3}


def tier_has_access(agent_tier: str | TierName, required_tier: str | TierName) -> bool:
    """Return True if agent_tier meets or exceeds required_tier."""
    if isinstance(agent_tier, str):
        agent_tier = TierName(agent_tier)
    if isinstance(required_tier, str):
        required_tier = TierName(required_tier)
    return _TIER_ORDER[agent_tier] >= _TIER_ORDER[required_tier]
