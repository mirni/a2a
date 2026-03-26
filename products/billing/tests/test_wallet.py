"""Tests for the Wallet operations."""

from __future__ import annotations

import pytest

from src.wallet import InsufficientCreditsError, Wallet, WalletNotFoundError


class TestWalletCreate:
    async def test_create_wallet(self, wallet: Wallet):
        result = await wallet.create("agent-1", initial_balance=100.0)
        assert result["agent_id"] == "agent-1"
        assert result["balance"] == 100.0

    async def test_create_wallet_zero_balance(self, wallet: Wallet):
        result = await wallet.create("agent-2")
        assert result["balance"] == 0.0

    async def test_create_duplicate_raises(self, wallet: Wallet):
        await wallet.create("agent-1")
        with pytest.raises(ValueError, match="already exists"):
            await wallet.create("agent-1")


class TestWalletBalance:
    async def test_get_balance(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        balance = await wallet.get_balance("agent-1")
        assert balance == 50.0

    async def test_get_balance_missing_wallet(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError):
            await wallet.get_balance("nonexistent")


class TestWalletDeposit:
    async def test_deposit_increases_balance(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        new_balance = await wallet.deposit("agent-1", 25.0, "top-up")
        assert new_balance == 75.0
        assert await wallet.get_balance("agent-1") == 75.0

    async def test_deposit_zero_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        with pytest.raises(ValueError, match="positive"):
            await wallet.deposit("agent-1", 0)

    async def test_deposit_negative_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        with pytest.raises(ValueError, match="positive"):
            await wallet.deposit("agent-1", -10.0)

    async def test_deposit_missing_wallet_raises(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError):
            await wallet.deposit("nonexistent", 10.0)


class TestWalletWithdraw:
    async def test_withdraw_decreases_balance(self, wallet: Wallet):
        await wallet.create("agent-1", 100.0)
        new_balance = await wallet.withdraw("agent-1", 30.0, "payout")
        assert new_balance == 70.0

    async def test_withdraw_insufficient_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 10.0)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await wallet.withdraw("agent-1", 50.0)
        assert exc_info.value.requested == 50.0
        assert exc_info.value.available == 10.0

    async def test_withdraw_zero_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        with pytest.raises(ValueError, match="positive"):
            await wallet.withdraw("agent-1", 0)

    async def test_withdraw_missing_wallet_raises(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError):
            await wallet.withdraw("nonexistent", 10.0)


class TestWalletCharge:
    async def test_charge_deducts(self, wallet: Wallet):
        await wallet.create("agent-1", 100.0)
        new_balance = await wallet.charge("agent-1", 15.0, "api call")
        assert new_balance == 85.0

    async def test_charge_insufficient_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 5.0)
        with pytest.raises(InsufficientCreditsError):
            await wallet.charge("agent-1", 10.0)

    async def test_charge_zero_raises(self, wallet: Wallet):
        await wallet.create("agent-1", 50.0)
        with pytest.raises(ValueError, match="positive"):
            await wallet.charge("agent-1", 0)

    async def test_charge_missing_wallet_raises(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError):
            await wallet.charge("nonexistent", 1.0)


class TestWalletTransactions:
    async def test_transactions_recorded(self, wallet: Wallet):
        await wallet.create("agent-1", 100.0)
        await wallet.deposit("agent-1", 50.0, "bonus")
        await wallet.withdraw("agent-1", 20.0, "cash out")
        txs = await wallet.get_transactions("agent-1")
        # initial deposit + deposit + withdrawal = 3 transactions
        assert len(txs) == 3
        types = [t["tx_type"] for t in txs]
        assert "deposit" in types
        assert "withdrawal" in types

    async def test_transactions_missing_wallet_raises(self, wallet: Wallet):
        with pytest.raises(WalletNotFoundError):
            await wallet.get_transactions("nonexistent")
