"""Centralized pricing configuration loader.

Loads all pricing data from the canonical pricing.json at the repo root.
Every consumer (tiers, billing, gateway config, onboarding) should read
values from PricingConfig rather than hardcoding numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Default location: repo-root/pricing.json
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "pricing.json"


class PricingConfig:
    """Read-only accessor for the centralized pricing.json."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    # --- Section accessors ---

    @property
    def tiers(self) -> dict[str, Any]:
        return self._data["tiers"]

    @property
    def subscription_plans(self) -> dict[str, Any]:
        return self._data["subscription_plans"]

    @property
    def credits(self) -> dict[str, Any]:
        return self._data["credits"]

    @property
    def stripe_packages(self) -> dict[str, Any]:
        return self._data["stripe_packages"]

    @property
    def volume_discounts(self) -> list[dict[str, Any]]:
        return self._data["volume_discounts"]

    @property
    def auto_reload(self) -> dict[str, Any]:
        return self._data["auto_reload"]

    @property
    def budget(self) -> dict[str, Any]:
        return self._data["budget"]

    # --- Convenience methods ---

    def get_volume_discount(self, call_count: int) -> int:
        """Return discount percentage for a given historical call count."""
        for tier in self.volume_discounts:
            if call_count >= tier["min_calls"]:
                return tier["discount_percent"]
        return 0


def load_pricing_config(path: Path | None = None) -> PricingConfig:
    """Load pricing config from JSON file.

    Args:
        path: Override path. Defaults to repo-root/pricing.json.

    Returns:
        PricingConfig instance.

    Raises:
        FileNotFoundError: If the pricing file doesn't exist.
    """
    p = path or _DEFAULT_PATH
    if not p.exists():
        raise FileNotFoundError(f"Pricing config not found: {p}")
    data = json.loads(p.read_text())
    return PricingConfig(data)
