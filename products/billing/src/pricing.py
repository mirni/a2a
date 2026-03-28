"""Pricing utilities — volume discounts and cost calculations.

Extracted from gateway tools to keep business logic in the product layer.
"""

from __future__ import annotations


def get_discount_tier(call_count: int) -> int:
    """Return discount percentage based on historical call count.

    Tiers:
        >= 1000 calls → 15%
        >= 500 calls  → 10%
        >= 100 calls  → 5%
        < 100 calls   → 0%
    """
    if call_count >= 1000:
        return 15
    if call_count >= 500:
        return 10
    if call_count >= 100:
        return 5
    return 0
