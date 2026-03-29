"""Tests for 500 free credits on signup (TDD).

Verifies that new wallets receive a signup bonus from pricing.json.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestSignupBonus:
    """Wallet creation should grant signup_bonus credits from pricing.json."""

    async def test_new_wallet_gets_signup_bonus(self, wallet):
        """Creating a wallet with default params grants the signup bonus."""
        result = await wallet.create("agent-new")
        # pricing.json: credits.signup_bonus = 500
        assert result["balance"] == 500.0

    async def test_signup_bonus_recorded_as_transaction(self, wallet, storage):
        """The signup bonus should appear as a 'signup_bonus' transaction."""
        await wallet.create("agent-txn")
        txns = await storage.get_transactions("agent-txn")
        bonus_txns = [t for t in txns if t["tx_type"] == "signup_bonus"]
        assert len(bonus_txns) == 1
        assert bonus_txns[0]["amount"] == 500.0

    async def test_signup_bonus_event_emitted(self, wallet, storage):
        """A wallet.signup_bonus event should be emitted."""
        await wallet.create("agent-evt")
        events = await storage.get_pending_events(limit=10)
        bonus_events = [e for e in events if e["event_type"] == "wallet.signup_bonus"]
        assert len(bonus_events) == 1

    async def test_explicit_initial_balance_added_to_bonus(self, wallet):
        """If initial_balance is passed, it stacks on top of signup bonus."""
        result = await wallet.create("agent-extra", initial_balance=100.0)
        assert result["balance"] == 600.0  # 500 bonus + 100 initial

    async def test_no_bonus_when_disabled(self, wallet):
        """When signup_bonus=False, no bonus credits are granted."""
        result = await wallet.create("agent-no-bonus", signup_bonus=False)
        assert result["balance"] == 0.0

    async def test_no_bonus_when_disabled_with_initial(self, wallet):
        """When signup_bonus=False but initial_balance set, only initial is used."""
        result = await wallet.create("agent-init-only", initial_balance=50.0, signup_bonus=False)
        assert result["balance"] == 50.0
