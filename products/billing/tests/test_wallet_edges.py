"""Edge case tests for the Wallet.

Covers: withdraw exact balance, withdraw balance+epsilon, deposit to
non-existent wallet, charge 0 credits, and double create.
"""

from __future__ import annotations

import pytest
from src.wallet import InsufficientCreditsError, Wallet, WalletNotFoundError


class TestWithdrawExactBalance:
    """Withdraw the entire balance — should succeed and leave balance=0."""

    async def test_withdraw_exact_balance_succeeds(self, wallet: Wallet):
        await wallet.create("agent-exact", initial_balance=100.0, signup_bonus=False)
        new_balance = await wallet.withdraw("agent-exact", 100.0)
        assert new_balance == 0.0
        assert await wallet.get_balance("agent-exact") == 0.0


class TestWithdrawBalancePlusEpsilon:
    """Withdraw balance + 0.01 — should fail with InsufficientCreditsError."""

    async def test_withdraw_slightly_over_raises(self, wallet: Wallet):
        await wallet.create("agent-over", initial_balance=100.0, signup_bonus=False)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await wallet.withdraw("agent-over", 100.01)
        assert exc_info.value.requested == 100.01
        assert exc_info.value.available == 100.0
        # Balance should remain unchanged
        assert await wallet.get_balance("agent-over") == 100.0


class TestDepositToNonExistent:
    """Deposit to a wallet that does not exist — should raise WalletNotFoundError."""

    async def test_deposit_nonexistent_raises(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError) as exc_info:
            await wallet.deposit("ghost-agent", 50.0, "bonus")
        assert exc_info.value.agent_id == "ghost-agent"


class TestChargeZeroCredits:
    """Charge 0 credits — the wallet.charge method raises ValueError
    for amount <= 0, so this verifies that behavior."""

    async def test_charge_zero_raises_value_error(self, wallet: Wallet):
        await wallet.create("agent-zero", initial_balance=100.0, signup_bonus=False)
        with pytest.raises(ValueError, match="positive"):
            await wallet.charge("agent-zero", 0)
        # Balance remains unchanged
        assert await wallet.get_balance("agent-zero") == 100.0


class TestDoubleCreate:
    """Creating a wallet twice with the same agent_id should raise ValueError."""

    async def test_double_create_raises(self, wallet: Wallet):
        await wallet.create("agent-dup", initial_balance=50.0, signup_bonus=False)
        with pytest.raises(ValueError, match="already exists"):
            await wallet.create("agent-dup", initial_balance=100.0, signup_bonus=False)
        # Original balance preserved
        assert await wallet.get_balance("agent-dup") == 50.0


class TestWithdrawAndChargeZeroBalance:
    """Edge case: wallet has balance 0, trying to withdraw or charge any
    positive amount should fail."""

    async def test_withdraw_from_zero_balance(self, wallet: Wallet):
        await wallet.create("agent-zero-bal", initial_balance=0.0, signup_bonus=False)
        with pytest.raises(InsufficientCreditsError):
            await wallet.withdraw("agent-zero-bal", 0.01)

    async def test_charge_from_zero_balance(self, wallet: Wallet):
        await wallet.create("agent-zero-ch", initial_balance=0.0, signup_bonus=False)
        with pytest.raises(InsufficientCreditsError):
            await wallet.charge("agent-zero-ch", 0.01)


class TestSmallAmounts:
    """Very small amounts should work correctly with floating point."""

    async def test_deposit_and_withdraw_small_amounts(self, wallet: Wallet):
        await wallet.create("agent-small", initial_balance=0.0, signup_bonus=False)
        await wallet.deposit("agent-small", 0.001)
        balance = await wallet.get_balance("agent-small")
        assert abs(balance - 0.001) < 1e-9

        new_balance = await wallet.withdraw("agent-small", 0.001)
        assert abs(new_balance) < 1e-9
