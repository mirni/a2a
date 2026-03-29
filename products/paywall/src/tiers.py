"""Tier definitions: free, pro, enterprise with rate limits and features.

Values are loaded from the canonical pricing.json at the repo root.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from shared_src.pricing_config import load_pricing_config


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


def _load_tier_configs() -> dict[TierName, TierConfig]:
    """Build TIER_CONFIGS from pricing.json."""
    cfg = load_pricing_config()
    result: dict[TierName, TierConfig] = {}
    for name_str, vals in cfg.tiers.items():
        tier_name = TierName(name_str)
        result[tier_name] = TierConfig(
            name=tier_name,
            rate_limit_per_hour=vals["rate_limit_per_hour"],
            cost_per_call=vals["cost_per_call"],
            audit_log_retention_days=vals.get("audit_log_retention_days"),
            support_level=vals["support_level"],
            burst_allowance=vals.get("burst_allowance", 10),
        )
    return result


# ---------------------------------------------------------------------------
# Tier registry — loaded from pricing.json
# ---------------------------------------------------------------------------

TIER_CONFIGS: dict[TierName, TierConfig] = _load_tier_configs()


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
