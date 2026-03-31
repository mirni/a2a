"""Tests verifying transaction isolation for financial operations.

Ensures:
- Concurrent withdrawals don't cause double-spend (race condition test)
- Balance never goes negative during concurrent operations
- Failed operations are properly rolled back
- Atomic SQL operations prevent race conditions
- IMMEDIATE transaction mode is used for multi-step financial operations
"""

from __future__ import annotations

import asyncio

import pytest
from src.storage import StorageBackend
from src.wallet import InsufficientCreditsError, Wallet

pytestmark = pytest.mark.asyncio


class TestConcurrentWithdrawNoDoublespend:
    """Concurrent withdrawals must not cause double-spend."""

    async def test_concurrent_withdrawals_only_one_succeeds(self, wallet: Wallet):
        """Multiple concurrent withdrawals of full balance — only one must succeed."""
        await wallet.create("alice", initial_balance=10.0, signup_bonus=False)

        async def try_withdraw() -> str:
            try:
                await wallet.withdraw("alice", 10.0, "concurrent")
                return "ok"
            except InsufficientCreditsError:
                return "insufficient"

        results = await asyncio.gather(*[try_withdraw() for _ in range(5)])
        successes = results.count("ok")
        failures = results.count("insufficient")

        assert successes == 1, f"Expected exactly 1 success, got {successes}"
        assert failures == 4

        balance = await wallet.get_balance("alice")
        assert balance == 0.0

    async def test_many_small_concurrent_withdrawals(self, wallet: Wallet):
        """Many concurrent small withdrawals should not overdraft."""
        await wallet.create("agent-many", initial_balance=100.0, signup_bonus=False)

        success_count = 0

        async def try_withdraw() -> None:
            nonlocal success_count
            try:
                await wallet.withdraw("agent-many", 20.0)
                success_count += 1
            except InsufficientCreditsError:
                pass

        # 10 concurrent withdrawals of 20 from a 100 balance
        await asyncio.gather(*[try_withdraw() for _ in range(10)])

        assert success_count <= 5, f"More than 5 succeeded: {success_count}"
        balance = await wallet.get_balance("agent-many")
        assert balance >= 0, f"Balance went negative: {balance}"
        assert balance == 100.0 - (success_count * 20.0)


class TestBalanceNeverNegative:
    """Balance must never go negative during concurrent operations."""

    async def test_mixed_concurrent_ops_balance_non_negative(self, wallet: Wallet):
        """Run deposits, withdrawals, and charges concurrently.

        Balance must never go negative at the end of the operations.
        """
        await wallet.create("agent-1", initial_balance=50.0, signup_bonus=False)

        async def do_deposit():
            await wallet.deposit("agent-1", 5.0, "concurrent deposit")
            return "deposit_ok"

        async def do_withdraw():
            try:
                await wallet.withdraw("agent-1", 8.0, "concurrent withdraw")
                return "withdraw_ok"
            except InsufficientCreditsError:
                return "withdraw_fail"

        async def do_charge():
            try:
                await wallet.charge("agent-1", 3.0, "concurrent charge")
                return "charge_ok"
            except InsufficientCreditsError:
                return "charge_fail"

        tasks = []
        for _ in range(5):
            tasks.append(do_deposit())
            tasks.append(do_withdraw())
            tasks.append(do_charge())

        results = await asyncio.gather(*tasks)
        balance = await wallet.get_balance("agent-1")

        assert balance >= 0.0, f"Balance went negative: {balance}"

        # Verify consistency: balance = initial + deposits - withdrawals - charges
        deposit_count = results.count("deposit_ok")
        withdraw_count = results.count("withdraw_ok")
        charge_count = results.count("charge_ok")
        expected = 50.0 + (deposit_count * 5.0) - (withdraw_count * 8.0) - (charge_count * 3.0)
        assert abs(balance - expected) < 1e-9, f"Balance {balance} != expected {expected}"


class TestAtomicDebitStrictSQL:
    """The atomic_debit_strict SQL prevents overdraft at DB level."""

    async def test_debit_fails_when_insufficient(self, storage: StorageBackend):
        """atomic_debit_strict returns (False, balance) when insufficient."""
        await storage.create_wallet("agent-strict", initial_balance=50.0)
        success, _balance = await storage.atomic_debit_strict("agent-strict", 100.0)
        assert success is False

        # Balance should be unchanged
        wallet_data = await storage.get_wallet("agent-strict")
        assert wallet_data["balance"] >= 50.0

    async def test_debit_succeeds_when_sufficient(self, storage: StorageBackend):
        """atomic_debit_strict returns (True, new_balance) when sufficient."""
        await storage.create_wallet("agent-strict2", initial_balance=100.0)
        success, new_balance = await storage.atomic_debit_strict("agent-strict2", 30.0)
        assert success is True
        assert new_balance == 70.0


class TestFailedOperationRollback:
    """Failed operations must not leave partial state."""

    async def test_withdraw_insufficient_leaves_balance_unchanged(self, wallet: Wallet):
        """If withdrawal fails due to insufficient funds, balance stays the same."""
        await wallet.create("alice", initial_balance=100.0, signup_bonus=False)

        with pytest.raises(InsufficientCreditsError):
            await wallet.withdraw("alice", 200.0)

        assert await wallet.get_balance("alice") == 100.0

    async def test_deposit_negative_amount_raises(self, wallet: Wallet):
        """Depositing zero or negative should raise ValueError."""
        await wallet.create("alice", initial_balance=100.0, signup_bonus=False)

        with pytest.raises(ValueError, match="positive"):
            await wallet.deposit("alice", 0.0)

        assert await wallet.get_balance("alice") == 100.0

    async def test_withdraw_negative_amount_raises(self, wallet: Wallet):
        """Withdrawing zero or negative should raise ValueError."""
        await wallet.create("alice", initial_balance=100.0, signup_bonus=False)

        with pytest.raises(ValueError, match="positive"):
            await wallet.withdraw("alice", -10.0)

        assert await wallet.get_balance("alice") == 100.0


class _MockExchangeService:
    """Mock exchange service that converts at a fixed 1:1 rate."""

    async def convert(self, amount, from_currency, to_currency):
        from decimal import Decimal
        from unittest.mock import MagicMock

        result = MagicMock()
        result.amount = Decimal(str(amount))
        return result


class TestConvertCurrencyAtomicity:
    """convert_currency must be atomic — no partial state on failure."""

    async def test_successful_conversion_updates_both(self, wallet: Wallet):
        """Successful conversion changes both currency balances."""
        await wallet.create("agent-convert", initial_balance=1000.0, signup_bonus=False)

        exchange = _MockExchangeService()
        await wallet.convert_currency("agent-convert", 100.0, "CREDITS", "USD", exchange)

        credits_bal = await wallet.get_balance("agent-convert", currency="CREDITS")
        usd_bal = await wallet.get_balance("agent-convert", currency="USD")

        assert credits_bal == 900.0
        assert usd_bal > 0

    async def test_conversion_insufficient_funds_no_partial_state(self, wallet: Wallet):
        """If source currency is insufficient, no partial state remains."""
        await wallet.create("agent-noconvert", initial_balance=10.0, signup_bonus=False)

        exchange = _MockExchangeService()
        with pytest.raises(InsufficientCreditsError):
            await wallet.convert_currency("agent-noconvert", 1000.0, "CREDITS", "USD", exchange)

        # Balance should be unchanged
        balance = await wallet.get_balance("agent-noconvert")
        assert balance == 10.0


class TestImmediateTransactionMode:
    """convert_currency must use BEGIN IMMEDIATE for its multi-step transaction."""

    async def test_convert_currency_uses_begin_immediate(self, wallet: Wallet):
        """The convert_currency source code must contain BEGIN IMMEDIATE."""
        import inspect

        source = inspect.getsource(wallet.convert_currency)
        assert "BEGIN IMMEDIATE" in source, "convert_currency() must use BEGIN IMMEDIATE for transaction isolation"
