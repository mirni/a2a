"""Tests for the money module — integer-based monetary arithmetic (TDD)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.money import (
    SCALE,
    atomic_to_credits,
    atomic_to_float,
    credits_to_atomic,
    split_amount,
    validate_non_negative,
)


class TestConstants:
    def test_scale_is_10e8(self):
        assert SCALE == 100_000_000

    def test_scale_is_int(self):
        assert isinstance(SCALE, int)


class TestCreditsToAtomic:
    def test_integer_credits(self):
        assert credits_to_atomic(Decimal("1")) == 100_000_000

    def test_fractional_credits(self):
        assert credits_to_atomic(Decimal("0.5")) == 50_000_000

    def test_small_credits(self):
        assert credits_to_atomic(Decimal("0.00000001")) == 1

    def test_large_credits(self):
        assert credits_to_atomic(Decimal("1000000")) == 100_000_000_000_000

    def test_zero(self):
        assert credits_to_atomic(Decimal("0")) == 0

    def test_returns_int(self):
        result = credits_to_atomic(Decimal("1.5"))
        assert isinstance(result, int)

    def test_from_float_string(self):
        # Common pattern: converting from float via string
        assert credits_to_atomic(Decimal("9.99")) == 999_000_000

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="[Nn]egative"):
            credits_to_atomic(Decimal("-1"))

    def test_accepts_int_input(self):
        assert credits_to_atomic(10) == 1_000_000_000

    def test_accepts_str_input(self):
        assert credits_to_atomic("10.5") == 1_050_000_000


class TestAtomicToCredits:
    def test_round_trip(self):
        original = Decimal("9.99")
        atomic = credits_to_atomic(original)
        restored = atomic_to_credits(atomic)
        assert restored == original

    def test_one_atomic_unit(self):
        result = atomic_to_credits(1)
        assert result == Decimal("0.00000001")

    def test_zero(self):
        assert atomic_to_credits(0) == Decimal("0")

    def test_returns_decimal(self):
        result = atomic_to_credits(100_000_000)
        assert isinstance(result, Decimal)

    def test_large_value(self):
        result = atomic_to_credits(100_000_000_000_000)
        assert result == Decimal("1000000")


class TestAtomicToFloat:
    def test_basic(self):
        result = atomic_to_float(100_000_000)
        assert result == 1.0

    def test_fractional(self):
        result = atomic_to_float(50_000_000)
        assert abs(result - 0.5) < 1e-10

    def test_returns_float(self):
        assert isinstance(atomic_to_float(1), float)


class TestSplitAmount:
    """Per P1-3: ``split_amount`` guarantees ``sum(slices) == total``.

    The last slice absorbs any rounding remainder so no cents ever
    disappear or materialise out of thin air.
    """

    def test_two_way_even(self) -> None:
        slices = split_amount(Decimal("10"), [Decimal("0.5"), Decimal("0.5")])
        assert slices == [Decimal("5"), Decimal("5")]
        assert sum(slices) == Decimal("10")

    def test_three_way_uneven_absorbs_remainder(self) -> None:
        # 0.3333… × 3 would lose a cent on 1.00. split_amount absorbs it
        # into the final slice so the sum is exact.
        ratios = [Decimal("1") / Decimal("3")] * 3
        slices = split_amount(Decimal("1.00"), ratios)
        assert sum(slices) == Decimal("1.00")
        assert len(slices) == 3

    def test_returns_decimal_list(self) -> None:
        slices = split_amount(Decimal("9.99"), [Decimal("0.5"), Decimal("0.5")])
        assert all(isinstance(s, Decimal) for s in slices)

    def test_zero_total(self) -> None:
        slices = split_amount(Decimal("0"), [Decimal("0.3"), Decimal("0.7")])
        assert slices == [Decimal("0"), Decimal("0")]

    def test_single_slice(self) -> None:
        slices = split_amount(Decimal("42.00"), [Decimal("1")])
        assert slices == [Decimal("42.00")]

    def test_rejects_negative_total(self) -> None:
        with pytest.raises(ValueError, match="[Nn]egative"):
            split_amount(Decimal("-1"), [Decimal("1")])

    def test_rejects_negative_ratio(self) -> None:
        with pytest.raises(ValueError, match="[Nn]egative"):
            split_amount(Decimal("1"), [Decimal("-0.5"), Decimal("1.5")])

    def test_rejects_ratios_not_summing_to_one(self) -> None:
        with pytest.raises(ValueError, match="ratios"):
            split_amount(Decimal("1"), [Decimal("0.3"), Decimal("0.3")])

    def test_rejects_empty_ratios(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            split_amount(Decimal("1"), [])

    def test_rejects_float_ratio(self) -> None:
        # Type guard: splitting on float is the exact bug we are avoiding.
        with pytest.raises(TypeError):
            split_amount(Decimal("1"), [0.5, 0.5])  # type: ignore[list-item]

    @settings(max_examples=200)
    @given(
        total_atomic=st.integers(min_value=0, max_value=10**14),
        weights=st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=8),
    )
    def test_hypothesis_sum_invariant(self, total_atomic: int, weights: list[int]) -> None:
        """Property: Σ slices == total for any valid ratio partition."""
        total = Decimal(total_atomic) / Decimal(SCALE)
        weight_sum = Decimal(sum(weights))
        ratios = [Decimal(w) / weight_sum for w in weights]
        slices = split_amount(total, ratios)
        assert sum(slices) == total
        assert len(slices) == len(ratios)
        assert all(s >= Decimal("0") for s in slices)


class TestValidateNonNegative:
    def test_positive_passes(self):
        validate_non_negative(100, "test")  # Should not raise

    def test_zero_passes(self):
        validate_non_negative(0, "test")  # Should not raise

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="test"):
            validate_non_negative(-1, "test")
