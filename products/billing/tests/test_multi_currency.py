"""Tests for multi-currency support.

Covers Currency enum, CurrencyAmount, ExchangeRate models,
ExchangeRateService, multi-currency wallet operations, and
cross-currency conversions.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.exchange import (
    ExchangeRateService,
    UnsupportedCurrencyError,
)
from src.models import Currency, CurrencyAmount, ExchangeRate
from src.storage import StorageBackend
from src.wallet import InsufficientCreditsError, Wallet

# ---------------------------------------------------------------------------
# Currency model tests
# ---------------------------------------------------------------------------


class TestCurrencyEnum:
    """Test the Currency enum and CurrencyAmount / ExchangeRate models."""

    def test_supported_currencies(self):
        """All seven currencies must be present."""
        expected = {"CREDITS", "USD", "EUR", "GBP", "BTC", "ETH", "USDC"}
        actual = {c.value for c in Currency}
        assert actual == expected

    def test_credits_is_default(self):
        """CREDITS should be usable as a default."""
        assert Currency("CREDITS") == Currency.CREDITS

    def test_max_decimal_places_fiat(self):
        """Fiat currencies (USD, EUR, GBP, CREDITS) allow 2 dp."""
        for cur in (Currency.USD, Currency.EUR, Currency.GBP, Currency.CREDITS):
            assert cur.max_decimal_places == 2, f"{cur} should allow 2 dp"

    def test_max_decimal_places_crypto(self):
        """BTC and ETH allow 8 dp, USDC allows 6 dp."""
        assert Currency.BTC.max_decimal_places == 8
        assert Currency.ETH.max_decimal_places == 8
        assert Currency.USDC.max_decimal_places == 6

    def test_currency_amount_creation(self):
        """CurrencyAmount holds a Decimal amount and a Currency."""
        ca = CurrencyAmount(amount=Decimal("49.99"), currency=Currency.USD)
        assert ca.amount == Decimal("49.99")
        assert ca.currency == Currency.USD

    def test_currency_amount_uses_decimal(self):
        """CurrencyAmount.amount must be Decimal, not float."""
        ca = CurrencyAmount(amount=Decimal("0.00000001"), currency=Currency.BTC)
        assert isinstance(ca.amount, Decimal)
        assert ca.amount == Decimal("0.00000001")

    def test_currency_amount_extra_fields_forbidden(self):
        """extra='forbid' should reject unknown fields."""
        with pytest.raises(Exception):  # ValidationError
            CurrencyAmount(amount=Decimal("10"), currency=Currency.USD, foo="bar")

    def test_currency_amount_json_schema_extra(self):
        """Model must include json_schema_extra for documentation."""
        schema = CurrencyAmount.model_json_schema()
        assert "examples" in schema or "example" in schema or "$defs" in schema
        # Check via model_config
        cfg = CurrencyAmount.model_config
        assert cfg.get("json_schema_extra") is not None

    def test_exchange_rate_creation(self):
        """ExchangeRate model stores from/to currencies and a Decimal rate."""
        er = ExchangeRate(
            from_currency=Currency.USD,
            to_currency=Currency.CREDITS,
            rate=Decimal("100"),
        )
        assert er.from_currency == Currency.USD
        assert er.to_currency == Currency.CREDITS
        assert er.rate == Decimal("100")

    def test_exchange_rate_has_updated_at(self):
        """ExchangeRate must track when the rate was last updated."""
        er = ExchangeRate(
            from_currency=Currency.USD,
            to_currency=Currency.EUR,
            rate=Decimal("0.92"),
        )
        assert er.updated_at is not None
        assert isinstance(er.updated_at, float)

    def test_exchange_rate_extra_fields_forbidden(self):
        """extra='forbid' should reject unknown fields."""
        with pytest.raises(Exception):
            ExchangeRate(
                from_currency=Currency.USD,
                to_currency=Currency.EUR,
                rate=Decimal("0.92"),
                foo="bar",
            )

    def test_exchange_rate_json_schema_extra(self):
        """Model must include json_schema_extra for documentation."""
        cfg = ExchangeRate.model_config
        assert cfg.get("json_schema_extra") is not None


# ---------------------------------------------------------------------------
# ExchangeRateService tests
# ---------------------------------------------------------------------------


class TestExchangeRateService:
    """Tests for the ExchangeRateService."""

    async def test_default_rates_initialized(self, storage: StorageBackend):
        """After init, default exchange rates must be populated."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        rate = await svc.get_rate(Currency.USD, Currency.CREDITS)
        assert rate == Decimal("100")

    async def test_get_rate_identity(self, storage: StorageBackend):
        """Same-currency rate must be 1."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        rate = await svc.get_rate(Currency.USD, Currency.USD)
        assert rate == Decimal("1")

    async def test_get_rate_returns_decimal(self, storage: StorageBackend):
        """Rate must always be a Decimal."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        rate = await svc.get_rate(Currency.USD, Currency.CREDITS)
        assert isinstance(rate, Decimal)

    async def test_convert_usd_to_credits(self, storage: StorageBackend):
        """Converting 1 USD should give 100 CREDITS at default rate."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        result = await svc.convert(Decimal("1"), Currency.USD, Currency.CREDITS)
        assert isinstance(result, CurrencyAmount)
        assert result.currency == Currency.CREDITS
        assert result.amount == Decimal("100")

    async def test_convert_credits_to_usd(self, storage: StorageBackend):
        """Converting 100 CREDITS should give 1 USD at default rate."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        result = await svc.convert(Decimal("100"), Currency.CREDITS, Currency.USD)
        assert result.currency == Currency.USD
        assert result.amount == Decimal("1")

    async def test_convert_btc_precision_8_decimals(self, storage: StorageBackend):
        """BTC must maintain 8 decimal places of precision."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        # Convert a small amount of BTC to CREDITS
        result = await svc.convert(Decimal("0.00000001"), Currency.BTC, Currency.CREDITS)
        assert isinstance(result.amount, Decimal)
        # At default rate 1 BTC = 6_000_000 CREDITS, 0.00000001 BTC = 0.06 CREDITS
        assert result.amount == Decimal("0.06")

    async def test_set_rate(self, storage: StorageBackend):
        """Admin can update exchange rates."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        await svc.set_rate(Currency.USD, Currency.CREDITS, Decimal("150"))
        rate = await svc.get_rate(Currency.USD, Currency.CREDITS)
        assert rate == Decimal("150")

    async def test_set_rate_updates_inverse(self, storage: StorageBackend):
        """Setting a rate also updates the inverse direction."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        await svc.set_rate(Currency.USD, Currency.CREDITS, Decimal("200"))
        inverse = await svc.get_rate(Currency.CREDITS, Currency.USD)
        assert inverse == Decimal("0.005")  # 1/200

    async def test_convert_same_currency(self, storage: StorageBackend):
        """Converting same currency returns the same amount."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        result = await svc.convert(Decimal("42.50"), Currency.EUR, Currency.EUR)
        assert result.amount == Decimal("42.50")
        assert result.currency == Currency.EUR

    async def test_get_rate_two_hop_pivot_via_credits(self, storage: StorageBackend):
        """HIGH-5 regression: USD→ETH must resolve via CREDITS pivot.

        When no direct USD→ETH rate exists but USD→CREDITS and CREDITS→ETH
        do, ``get_rate`` must return the product (two-hop conversion).
        """
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        # Default rates seed USD<->CREDITS and ETH<->CREDITS but no direct
        # USD<->ETH row. The service must therefore fall back to the
        # two-hop pivot and return a non-zero product rate.
        rate = await svc.get_rate(Currency.USD, Currency.ETH)
        assert rate > Decimal("0")

        # The rate must equal rate(USD→CREDITS) * rate(CREDITS→ETH).
        usd_to_credits = await svc.get_rate(Currency.USD, Currency.CREDITS)
        credits_to_eth = await svc.get_rate(Currency.CREDITS, Currency.ETH)
        assert rate == usd_to_credits * credits_to_eth

    async def test_get_rate_two_hop_unsupported_when_leg_missing(self, storage: StorageBackend):
        """Two-hop fallback raises when one leg has no rate."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        # Delete the CREDITS→ETH leg so the two-hop path fails.
        await storage.db.execute(
            "DELETE FROM exchange_rates WHERE from_currency = ? AND to_currency = ?",
            (Currency.CREDITS.value, Currency.ETH.value),
        )
        # Also remove any direct USD→ETH row (there shouldn't be one, but
        # be defensive so this test stays meaningful as rates evolve).
        await storage.db.execute(
            "DELETE FROM exchange_rates WHERE from_currency = ? AND to_currency = ?",
            (Currency.USD.value, Currency.ETH.value),
        )
        await storage.db.commit()

        with pytest.raises(UnsupportedCurrencyError):
            await svc.get_rate(Currency.USD, Currency.ETH)


# ---------------------------------------------------------------------------
# Multi-currency wallet tests
# ---------------------------------------------------------------------------


class TestMultiCurrencyWallet:
    """Tests for wallet operations with currency parameter."""

    async def test_deposit_usd(self, wallet: Wallet, storage: StorageBackend):
        """Depositing in USD should update the USD balance."""
        await wallet.create("agent-mc-1", initial_balance=0.0, signup_bonus=False)
        new_balance = await wallet.deposit("agent-mc-1", 50.0, "usd deposit", currency="USD")
        assert new_balance == 50.0

    async def test_get_balance_currency_specific(self, wallet: Wallet, storage: StorageBackend):
        """get_balance returns currency-specific balance."""
        await wallet.create("agent-mc-2", initial_balance=100.0, signup_bonus=False)
        # Default balance is CREDITS
        credits_balance = await wallet.get_balance("agent-mc-2", currency="CREDITS")
        assert credits_balance == 100.0

        # USD balance should be 0 (no USD deposited)
        usd_balance = await wallet.get_balance("agent-mc-2", currency="USD")
        assert usd_balance == 0.0

    async def test_deposit_and_withdraw_usd(self, wallet: Wallet, storage: StorageBackend):
        """Deposit and withdraw in USD should work independently of CREDITS."""
        await wallet.create("agent-mc-3", initial_balance=100.0, signup_bonus=False)

        # Deposit USD
        await wallet.deposit("agent-mc-3", 50.0, "usd deposit", currency="USD")
        # Withdraw USD
        new_bal = await wallet.withdraw("agent-mc-3", 20.0, "usd withdraw", currency="USD")
        assert new_bal == 30.0

        # CREDITS balance should be unaffected
        credits_bal = await wallet.get_balance("agent-mc-3", currency="CREDITS")
        assert credits_bal == 100.0

    async def test_withdraw_insufficient_currency_balance(self, wallet: Wallet, storage: StorageBackend):
        """Withdrawing more than available in a specific currency should fail."""
        await wallet.create("agent-mc-4", initial_balance=100.0, signup_bonus=False)
        # Agent has 100 CREDITS, 0 USD
        with pytest.raises(InsufficientCreditsError):
            await wallet.withdraw("agent-mc-4", 10.0, "fail", currency="USD")

    async def test_multiple_currency_balances(self, wallet: Wallet, storage: StorageBackend):
        """An agent can hold balances in multiple currencies simultaneously."""
        await wallet.create("agent-mc-5", initial_balance=500.0, signup_bonus=False)

        await wallet.deposit("agent-mc-5", 100.0, "usd", currency="USD")
        await wallet.deposit("agent-mc-5", 80.0, "eur", currency="EUR")
        await wallet.deposit("agent-mc-5", 0.5, "btc", currency="BTC")

        assert await wallet.get_balance("agent-mc-5", currency="CREDITS") == 500.0
        assert await wallet.get_balance("agent-mc-5", currency="USD") == 100.0
        assert await wallet.get_balance("agent-mc-5", currency="EUR") == 80.0
        assert await wallet.get_balance("agent-mc-5", currency="BTC") == 0.5

    async def test_default_currency_is_credits(self, wallet: Wallet, storage: StorageBackend):
        """Operations without currency parameter default to CREDITS."""
        await wallet.create("agent-mc-6", initial_balance=50.0, signup_bonus=False)
        # No currency param -> CREDITS
        bal = await wallet.get_balance("agent-mc-6")
        assert bal == 50.0

        new_bal = await wallet.deposit("agent-mc-6", 10.0, "more credits")
        assert new_bal == 60.0


# ---------------------------------------------------------------------------
# Currency conversion via wallet
# ---------------------------------------------------------------------------


class TestConvertCurrencyWallet:
    """Tests for convert_currency: moving funds between currency balances."""

    async def test_convert_usd_to_credits(self, wallet: Wallet, storage: StorageBackend):
        """Convert USD balance to CREDITS using exchange rate."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        await wallet.create("agent-cv-1", initial_balance=0.0, signup_bonus=False)
        await wallet.deposit("agent-cv-1", 10.0, "usd", currency="USD")

        result = await wallet.convert_currency(
            "agent-cv-1",
            amount=10.0,
            from_currency="USD",
            to_currency="CREDITS",
            exchange_service=svc,
        )
        # 10 USD * 100 = 1000 CREDITS
        assert result["from_amount"] == 10.0
        assert result["to_amount"] == 1000.0
        assert result["from_currency"] == "USD"
        assert result["to_currency"] == "CREDITS"

        # USD balance should be 0
        assert await wallet.get_balance("agent-cv-1", currency="USD") == 0.0
        # CREDITS balance should be 1000
        assert await wallet.get_balance("agent-cv-1", currency="CREDITS") == 1000.0

    async def test_convert_insufficient_source_balance(self, wallet: Wallet, storage: StorageBackend):
        """Converting more than available in source currency should fail."""
        svc = ExchangeRateService(storage=storage)
        await svc.initialize_default_rates()

        await wallet.create("agent-cv-2", initial_balance=0.0, signup_bonus=False)
        await wallet.deposit("agent-cv-2", 5.0, "usd", currency="USD")

        with pytest.raises(InsufficientCreditsError):
            await wallet.convert_currency(
                "agent-cv-2",
                amount=10.0,
                from_currency="USD",
                to_currency="CREDITS",
                exchange_service=svc,
            )


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


class TestNegativeCurrency:
    """Negative test cases for currency operations."""

    def test_invalid_currency_string(self):
        """An unsupported currency string should raise an error."""
        with pytest.raises(ValueError):
            Currency("DOGECOIN")

    async def test_unsupported_currency_rate_lookup(self, storage: StorageBackend):
        """Looking up a rate for a pair with no rate set should raise."""
        svc = ExchangeRateService(storage=storage)
        # Don't initialize defaults -- no rates exist
        with pytest.raises(UnsupportedCurrencyError):
            await svc.get_rate(Currency.USD, Currency.CREDITS)
