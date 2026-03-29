"""Tests for the centralized pricing config loader.

Verifies that pricing.json is the single source of truth and that
all consumers load values from it correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.pricing_config import (
    PricingConfig,
    load_pricing_config,
)

PRICING_JSON = Path(__file__).resolve().parents[3] / "pricing.json"


class TestPricingJsonExists:
    """Ensure the canonical pricing.json file is valid."""

    def test_file_exists(self):
        assert PRICING_JSON.exists(), "pricing.json must exist at repo root"

    def test_valid_json(self):
        data = json.loads(PRICING_JSON.read_text())
        assert isinstance(data, dict)

    def test_required_sections(self):
        data = json.loads(PRICING_JSON.read_text())
        for section in ("tiers", "credits", "stripe_packages", "volume_discounts", "budget"):
            assert section in data, f"Missing section: {section}"


class TestLoadPricingConfig:
    """Test the PricingConfig loader."""

    def test_loads_from_default_path(self):
        cfg = load_pricing_config()
        assert isinstance(cfg, PricingConfig)

    def test_loads_from_explicit_path(self):
        cfg = load_pricing_config(PRICING_JSON)
        assert isinstance(cfg, PricingConfig)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_pricing_config(tmp_path / "nonexistent.json")


class TestTierConfig:
    """Verify tier values match pricing.json."""

    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_all_tiers_present(self, cfg: PricingConfig):
        assert set(cfg.tiers.keys()) == {"free", "starter", "pro", "enterprise"}

    def test_free_tier_values(self, cfg: PricingConfig):
        t = cfg.tiers["free"]
        assert t["rate_limit_per_hour"] == 100
        assert t["burst_allowance"] == 10
        assert t["support_level"] == "none"

    def test_enterprise_tier_values(self, cfg: PricingConfig):
        t = cfg.tiers["enterprise"]
        assert t["rate_limit_per_hour"] == 100_000
        assert t["burst_allowance"] == 1000
        assert t["support_level"] == "priority"

    def test_tier_ordering_monotonic(self, cfg: PricingConfig):
        """Rate limits must increase across tiers."""
        order = ["free", "starter", "pro", "enterprise"]
        limits = [cfg.tiers[t]["rate_limit_per_hour"] for t in order]
        assert limits == sorted(limits)
        assert len(set(limits)) == 4, "All tiers must have distinct rate limits"


class TestCreditsConfig:
    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_credits_per_dollar(self, cfg: PricingConfig):
        assert cfg.credits["per_dollar"] == 100

    def test_signup_bonus(self, cfg: PricingConfig):
        assert cfg.credits["signup_bonus"] == 500

    def test_min_less_than_max(self, cfg: PricingConfig):
        assert cfg.credits["min_purchase"] < cfg.credits["max_per_transaction"]


class TestStripePackages:
    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_all_packages_present(self, cfg: PricingConfig):
        assert set(cfg.stripe_packages.keys()) == {"starter", "growth", "scale", "enterprise"}

    def test_price_per_credit_decreasing(self, cfg: PricingConfig):
        """Larger packages should offer better per-credit pricing."""
        order = ["starter", "growth", "scale", "enterprise"]
        ratios = [
            cfg.stripe_packages[p]["price_cents"] / cfg.stripe_packages[p]["credits"]
            for p in order
        ]
        for i in range(len(ratios) - 1):
            assert ratios[i] >= ratios[i + 1], (
                f"Package {order[i+1]} should be cheaper per-credit than {order[i]}"
            )


class TestVolumeDiscounts:
    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_sorted_descending_by_min_calls(self, cfg: PricingConfig):
        min_calls = [d["min_calls"] for d in cfg.volume_discounts]
        assert min_calls == sorted(min_calls, reverse=True)

    def test_get_discount_for_count(self, cfg: PricingConfig):
        assert cfg.get_volume_discount(2000) == 15
        assert cfg.get_volume_discount(500) == 10
        assert cfg.get_volume_discount(100) == 5
        assert cfg.get_volume_discount(50) == 0


class TestSubscriptionPlans:
    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_starter_plan(self, cfg: PricingConfig):
        plan = cfg.subscription_plans["starter_monthly"]
        assert plan["price_cents"] == 2900
        assert plan["credits_included"] == 3500
        assert plan["tier"] == "starter"

    def test_pro_plan(self, cfg: PricingConfig):
        plan = cfg.subscription_plans["pro_monthly"]
        assert plan["price_cents"] == 19900
        assert plan["credits_included"] == 25000
        assert plan["tier"] == "pro"


class TestAutoReload:
    @pytest.fixture()
    def cfg(self) -> PricingConfig:
        return load_pricing_config()

    def test_auto_reload_defaults(self, cfg: PricingConfig):
        assert cfg.auto_reload["default_threshold_credits"] == 100
        assert cfg.auto_reload["default_reload_credits"] == 1000
        assert cfg.auto_reload["enabled_by_default"] is False
