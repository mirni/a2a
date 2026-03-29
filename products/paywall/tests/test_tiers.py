"""Tests for tier definitions and access checks."""

from __future__ import annotations

import pytest
from src.tiers import (
    TIER_CONFIGS,
    TierName,
    get_tier_config,
    tier_has_access,
)


class TestTierName:
    def test_enum_values(self):
        assert TierName.FREE == "free"
        assert TierName.STARTER == "starter"
        assert TierName.PRO == "pro"
        assert TierName.ENTERPRISE == "enterprise"

    def test_enum_from_string(self):
        assert TierName("free") == TierName.FREE
        assert TierName("starter") == TierName.STARTER
        assert TierName("pro") == TierName.PRO
        assert TierName("enterprise") == TierName.ENTERPRISE

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError):
            TierName("platinum")


class TestTierConfigs:
    def test_all_tiers_defined(self):
        assert TierName.FREE in TIER_CONFIGS
        assert TierName.STARTER in TIER_CONFIGS
        assert TierName.PRO in TIER_CONFIGS
        assert TierName.ENTERPRISE in TIER_CONFIGS

    def test_free_tier(self):
        cfg = TIER_CONFIGS[TierName.FREE]
        assert cfg.rate_limit_per_hour == 100
        assert cfg.cost_per_call == 0
        assert cfg.audit_log_retention_days is None
        assert cfg.support_level == "none"

    def test_starter_tier(self):
        cfg = TIER_CONFIGS[TierName.STARTER]
        assert cfg.rate_limit_per_hour == 1_000
        assert cfg.cost_per_call == 0
        assert cfg.audit_log_retention_days == 7
        assert cfg.support_level == "community"
        assert cfg.burst_allowance == 25

    def test_pro_tier(self):
        cfg = TIER_CONFIGS[TierName.PRO]
        assert cfg.rate_limit_per_hour == 10_000
        assert cfg.cost_per_call == 0
        assert cfg.audit_log_retention_days == 30
        assert cfg.support_level == "email"

    def test_enterprise_tier(self):
        cfg = TIER_CONFIGS[TierName.ENTERPRISE]
        assert cfg.rate_limit_per_hour == 100_000
        assert cfg.cost_per_call == 0
        assert cfg.audit_log_retention_days == 90
        assert cfg.support_level == "priority"

    def test_rate_limit_per_minute(self):
        free = TIER_CONFIGS[TierName.FREE]
        assert free.rate_limit_per_minute == 1  # 100/60 = 1 (max(1, 1))

        starter = TIER_CONFIGS[TierName.STARTER]
        assert starter.rate_limit_per_minute == 16  # 1000/60 = 16

        pro = TIER_CONFIGS[TierName.PRO]
        assert pro.rate_limit_per_minute == 166  # 10000/60 = 166

    def test_frozen_config(self):
        cfg = TIER_CONFIGS[TierName.FREE]
        with pytest.raises(AttributeError):
            cfg.rate_limit_per_hour = 999  # type: ignore[misc]


class TestGetTierConfig:
    def test_lookup_by_string(self):
        cfg = get_tier_config("free")
        assert cfg.name == TierName.FREE

    def test_lookup_by_enum(self):
        cfg = get_tier_config(TierName.PRO)
        assert cfg.name == TierName.PRO

    def test_unknown_tier_raises(self):
        with pytest.raises(ValueError, match="Unknown tier 'platinum'"):
            get_tier_config("platinum")


class TestTierHasAccess:
    def test_same_tier_access(self):
        assert tier_has_access("free", "free") is True
        assert tier_has_access("starter", "starter") is True
        assert tier_has_access("pro", "pro") is True
        assert tier_has_access("enterprise", "enterprise") is True

    def test_higher_tier_has_access(self):
        assert tier_has_access("starter", "free") is True
        assert tier_has_access("pro", "free") is True
        assert tier_has_access("pro", "starter") is True
        assert tier_has_access("enterprise", "free") is True
        assert tier_has_access("enterprise", "starter") is True
        assert tier_has_access("enterprise", "pro") is True

    def test_lower_tier_denied(self):
        assert tier_has_access("free", "starter") is False
        assert tier_has_access("free", "pro") is False
        assert tier_has_access("free", "enterprise") is False
        assert tier_has_access("starter", "pro") is False
        assert tier_has_access("starter", "enterprise") is False
        assert tier_has_access("pro", "enterprise") is False

    def test_accepts_enum(self):
        assert tier_has_access(TierName.PRO, TierName.FREE) is True
        assert tier_has_access(TierName.STARTER, TierName.FREE) is True
        assert tier_has_access(TierName.FREE, TierName.STARTER) is False
        assert tier_has_access(TierName.FREE, TierName.PRO) is False
