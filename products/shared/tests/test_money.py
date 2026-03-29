"""Tests for the money module — integer-based monetary arithmetic (TDD)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import pytest

from src.money import (
    SCALE,
    credits_to_atomic,
    atomic_to_credits,
    atomic_to_float,
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


class TestValidateNonNegative:
    def test_positive_passes(self):
        validate_non_negative(100, "test")  # Should not raise

    def test_zero_passes(self):
        validate_non_negative(0, "test")  # Should not raise

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="test"):
            validate_non_negative(-1, "test")
