"""Pricing utilities — volume discounts and cost calculations.

Values are loaded from the canonical pricing.json at the repo root.
"""

from __future__ import annotations

from shared_src.pricing_config import load_pricing_config

_pricing = load_pricing_config()


def get_discount_tier(call_count: int) -> int:
    """Return discount percentage based on historical call count."""
    return _pricing.get_volume_discount(call_count)
