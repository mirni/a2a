"""Integer-based monetary arithmetic.

All monetary values are stored as INTEGER in the database, representing
the smallest atomic unit.  1 credit = SCALE atomic units.

SCALE = 10^8 (100,000,000) — matches Bitcoin satoshi granularity and
provides 8 decimal places of precision for any currency.

Examples:
    1 credit      = 100_000_000 atomic units
    0.01 credits  = 1_000_000 atomic units
    1 BTC         = 100_000_000 satoshi (native!)
    1 USDC        = 100_000_000 atomic units (2 extra decimals beyond standard)
"""

from __future__ import annotations

from decimal import Decimal

# 10^8 — one credit equals 100 million atomic units.
# Matches Bitcoin's satoshi scale.  64-bit INTEGER can hold
# ±92 billion credits at this scale.
SCALE: int = 100_000_000


def credits_to_atomic(value: Decimal | int | str) -> int:
    """Convert a human-readable credit amount to atomic integer units.

    Raises ValueError if the value is negative.
    """
    d = Decimal(str(value))
    if d < 0:
        raise ValueError(f"Negative monetary value not allowed: {d}")
    return int(d * SCALE)


def atomic_to_credits(atomic: int) -> Decimal:
    """Convert atomic integer units back to a Decimal credit amount."""
    return Decimal(atomic) / Decimal(SCALE)


def atomic_to_float(atomic: int) -> float:
    """Convert atomic units to float (for API backward-compatibility only)."""
    return atomic / SCALE


def validate_non_negative(atomic: int, label: str = "amount") -> None:
    """Raise ValueError if the atomic value is negative."""
    if atomic < 0:
        raise ValueError(f"{label} must be non-negative, got {atomic}")
