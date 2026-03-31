"""Tests for atomic convert_currency operation (P1-5).

The convert_currency tool does a two-phase withdraw-then-deposit. If there's a
crash between phases, funds are lost. These tests verify that:
1. Successful conversion updates both wallets atomically
2. If the deposit step would fail, the withdraw is rolled back
3. Balances are consistent after conversion (no fund leakage)
4. Concurrent conversions don't cause race conditions
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio


def _ensure_billing_models_importable() -> None:
    """Ensure ``from .models import Currency`` works inside wallet.convert_currency.

    The bootstrap loader registers billing modules under ``billing_src.*`` but
    the wallet module's ``__package__`` still references ``src``, so relative
    imports like ``from .models import Currency`` resolve to ``src.models``
    which has been cleaned up.  Mirror the workaround from the gateway's
    ``_convert_currency`` tool handler.
    """
    if "billing_src.models" in sys.modules and "src.models" not in sys.modules:
        sys.modules["src.models"] = sys.modules["billing_src.models"]


class TestConvertCurrencyAtomic:
    """Verify convert_currency wraps withdraw+deposit in a single DB transaction."""

    async def test_successful_conversion_updates_both_balances(self, app, client, api_key):
        """A successful conversion should debit source and credit target atomically."""
        _ensure_billing_models_importable()
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        # Deposit 10 USD so we can convert
        await ctx.tracker.wallet.deposit("test-agent", 10.0, "seed USD", currency="USD")

        usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_before = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")
        assert usd_before == 10.0

        # Convert 5 USD -> CREDITS (rate 100:1 -> 500 CREDITS)
        result = await ctx.tracker.wallet.convert_currency(
            agent_id="test-agent",
            amount=5.0,
            from_currency="USD",
            to_currency="CREDITS",
            exchange_service=exchange_svc,
        )

        assert result["from_amount"] == 5.0
        assert result["to_amount"] == 500.0

        usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_after = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        assert usd_after == usd_before - 5.0
        assert credits_after == credits_before + 500.0

    async def test_deposit_failure_rolls_back_withdraw(self, app, client, api_key):
        """If deposit fails after withdraw, the withdraw must be rolled back.

        We simulate a deposit failure by monkey-patching _credit_in_txn
        to raise an exception after the debit has been applied within the
        transaction.  Because both operations share a single DB transaction,
        the rollback should restore the source balance.
        """
        _ensure_billing_models_importable()
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        # Deposit 10 USD
        await ctx.tracker.wallet.deposit("test-agent", 10.0, "seed USD", currency="USD")

        usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_before = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")
        assert usd_before == 10.0

        # Patch _credit_in_txn to fail (simulating a crash during the credit
        # step of the atomic conversion)
        async def failing_credit(db, agent_id, amt_atomic, currency, now):
            raise RuntimeError("Simulated deposit failure")

        with patch.object(ctx.tracker.storage, "_credit_in_txn", side_effect=failing_credit):
            with pytest.raises(RuntimeError, match="Simulated deposit failure"):
                await ctx.tracker.wallet.convert_currency(
                    agent_id="test-agent",
                    amount=5.0,
                    from_currency="USD",
                    to_currency="CREDITS",
                    exchange_service=exchange_svc,
                )

        # After failure, USD balance must be restored (no fund leakage)
        usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_after = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        assert usd_after == usd_before, (
            f"USD balance should be restored after deposit failure. Expected {usd_before}, got {usd_after}"
        )
        assert credits_after == credits_before, (
            f"CREDITS balance should be unchanged after deposit failure. Expected {credits_before}, got {credits_after}"
        )

    async def test_balances_consistent_after_conversion_no_leakage(self, app, client, api_key):
        """Total value (in CREDITS equivalent) must be conserved across conversion.

        Before: X USD + Y CREDITS
        After:  (X - amount) USD + (Y + amount * rate) CREDITS
        The total CREDITS equivalent must be the same.
        """
        _ensure_billing_models_importable()
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService
        from billing_src.models import Currency

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        # Deposit 20 USD
        await ctx.tracker.wallet.deposit("test-agent", 20.0, "seed USD", currency="USD")

        usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_before = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        usd_to_credits_rate = float(await exchange_svc.get_rate(Currency.USD, Currency.CREDITS))

        total_credits_before = credits_before + usd_before * usd_to_credits_rate

        # Convert 10 USD -> CREDITS
        await ctx.tracker.wallet.convert_currency(
            agent_id="test-agent",
            amount=10.0,
            from_currency="USD",
            to_currency="CREDITS",
            exchange_service=exchange_svc,
        )

        usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_after = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        total_credits_after = credits_after + usd_after * usd_to_credits_rate

        assert abs(total_credits_after - total_credits_before) < 0.01, (
            f"Total value leaked! Before: {total_credits_before}, After: {total_credits_after}"
        )

    async def test_concurrent_conversions_no_race_condition(self, app, client, api_key):
        """Multiple concurrent conversions should not cause balance inconsistencies.

        If two conversions happen simultaneously, each should see the correct
        balance and the final state should reflect both conversions.
        """
        _ensure_billing_models_importable()
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        # Deposit 100 USD
        await ctx.tracker.wallet.deposit("test-agent", 100.0, "seed USD", currency="USD")

        usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_before = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        # Run 5 conversions of 10 USD each concurrently
        async def do_convert():
            return await ctx.tracker.wallet.convert_currency(
                agent_id="test-agent",
                amount=10.0,
                from_currency="USD",
                to_currency="CREDITS",
                exchange_service=exchange_svc,
            )

        results = await asyncio.gather(*[do_convert() for _ in range(5)], return_exceptions=True)

        # Count successful conversions
        successes = [r for r in results if not isinstance(r, Exception)]

        # At least some should succeed (how many depends on timing)
        assert len(successes) > 0, "At least one concurrent conversion should succeed"

        usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_after = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        # Each successful conversion should have withdrawn 10 USD and deposited 1000 CREDITS
        expected_usd = usd_before - (len(successes) * 10.0)
        expected_credits = credits_before + (len(successes) * 1000.0)

        assert abs(usd_after - expected_usd) < 0.01, (
            f"USD balance mismatch after concurrent conversions. Expected {expected_usd}, got {usd_after}"
        )
        assert abs(credits_after - expected_credits) < 0.01, (
            f"CREDITS balance mismatch after concurrent conversions. Expected {expected_credits}, got {credits_after}"
        )

    async def test_invalid_target_currency_rolls_back(self, app, client, api_key):
        """If exchange service raises for invalid target currency, withdraw is rolled back."""
        _ensure_billing_models_importable()
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        # Intentionally do NOT initialize default rates so conversion will fail

        # Deposit 10 USD
        await ctx.tracker.wallet.deposit("test-agent", 10.0, "seed USD", currency="USD")

        usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_before = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        with pytest.raises(Exception):
            await ctx.tracker.wallet.convert_currency(
                agent_id="test-agent",
                amount=5.0,
                from_currency="USD",
                to_currency="CREDITS",
                exchange_service=exchange_svc,
            )

        # Balances should be unchanged
        usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        credits_after = await ctx.tracker.wallet.get_balance("test-agent", currency="CREDITS")

        assert usd_after == usd_before, (
            f"USD should be restored after exchange rate lookup failure. Expected {usd_before}, got {usd_after}"
        )
        assert credits_after == credits_before, (
            f"CREDITS should be unchanged after exchange rate lookup failure. "
            f"Expected {credits_before}, got {credits_after}"
        )
