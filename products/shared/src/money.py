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

from collections.abc import Sequence
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


def split_amount(total: Decimal, ratios: Sequence[Decimal]) -> list[Decimal]:
    """Split *total* into slices proportional to *ratios*, exactly.

    Guarantees::

        sum(split_amount(total, ratios)) == total

    for any non-negative ``total`` and any non-empty sequence of
    non-negative ``Decimal`` ratios that sum to 1. Rounding on the
    individual slices is absorbed by the final slice so no atomic
    units ever disappear or materialise.

    This is the building block P1-3 uses everywhere a payment has to
    be divided across recipients — capture splits, marketplace
    payouts, fee apportioning. The function intentionally refuses
    ``float`` ratios so that a future caller cannot accidentally
    reintroduce binary-float drift.

    Args:
        total: Non-negative ``Decimal`` amount to split.
        ratios: Non-empty sequence of non-negative ``Decimal`` ratios
            summing to ``Decimal("1")``.

    Returns:
        List of ``Decimal`` slices with the same length as ``ratios``
        whose sum is exactly ``total``.

    Raises:
        TypeError: if any ratio is not a ``Decimal``.
        ValueError: if *total* is negative, any ratio is negative,
            ratios is empty, or ratios do not sum to 1.
    """
    if total < 0:
        raise ValueError(f"Negative total not allowed: {total}")
    if not ratios:
        raise ValueError("ratios must not be empty")
    for r in ratios:
        if not isinstance(r, Decimal):
            raise TypeError(
                f"split_amount() ratios must be Decimal, got {type(r).__name__}. "
                "Convert with Decimal(str(ratio)) before calling."
            )
        if r < 0:
            raise ValueError(f"Negative ratio not allowed: {r}")
    ratio_sum = sum(ratios, Decimal("0"))
    # Tolerance guards against the common ``Decimal(1)/Decimal(3) * 3``
    # case which under Decimal precision sums to 0.999…9. Any ratio
    # set more than 10⁻¹⁸ off is rejected outright — that is already
    # 10 orders of magnitude tighter than our atomic unit (10⁻⁸).
    if abs(ratio_sum - Decimal("1")) > Decimal("1E-18"):
        raise ValueError(f"ratios must sum to 1, got {ratio_sum}")

    # Work in atomic units for an exact integer partition. Pick a
    # working scale big enough to preserve the input's precision.
    atomic_total = credits_to_atomic(total)
    slices_atomic: list[int] = []
    running = 0
    for r in ratios[:-1]:
        slice_atomic = int(Decimal(atomic_total) * r)
        slices_atomic.append(slice_atomic)
        running += slice_atomic
    # Final slice absorbs the rounding remainder so the sum is exact.
    slices_atomic.append(atomic_total - running)
    return [atomic_to_credits(s) for s in slices_atomic]
