"""Tests for auto-reload billing (TDD).

When balance drops below a threshold, automatically add credits.
Agents never run out of credits if auto-reload is enabled.
"""

from __future__ import annotations

import pytest
from src.wallet import Wallet

pytestmark = pytest.mark.asyncio


class TestAutoReloadConfig:
    """Test enabling/disabling auto-reload."""

    async def test_enable_auto_reload(self, wallet: Wallet, storage):
        await wallet.create("agent-ar", signup_bonus=False)
        await wallet.enable_auto_reload(
            "agent-ar",
            threshold=100.0,
            reload_amount=1000.0,
        )
        config = await wallet.get_auto_reload_config("agent-ar")
        assert config is not None
        assert config["threshold"] == 100.0
        assert config["reload_amount"] == 1000.0
        assert config["enabled"] is True

    async def test_disable_auto_reload(self, wallet: Wallet):
        await wallet.create("agent-dis", signup_bonus=False)
        await wallet.enable_auto_reload("agent-dis", threshold=100.0, reload_amount=1000.0)
        await wallet.disable_auto_reload("agent-dis")
        config = await wallet.get_auto_reload_config("agent-dis")
        assert config["enabled"] is False

    async def test_get_config_when_not_set(self, wallet: Wallet):
        await wallet.create("agent-noar", signup_bonus=False)
        config = await wallet.get_auto_reload_config("agent-noar")
        assert config is None


class TestAutoReloadOnCharge:
    """Verify auto-reload triggers when balance drops below threshold after charge."""

    async def test_charge_triggers_reload(self, wallet: Wallet):
        """Balance 200, threshold 100, charge 150 → balance drops to 50 → reload 1000 → 1050."""
        await wallet.create("agent-ch", initial_balance=200.0, signup_bonus=False)
        await wallet.enable_auto_reload("agent-ch", threshold=100.0, reload_amount=1000.0)

        new_balance = await wallet.charge("agent-ch", 150.0, "api call")
        # 200 - 150 = 50 (below threshold 100) → auto-reload 1000 → 1050
        assert new_balance == 1050.0

    async def test_charge_no_reload_above_threshold(self, wallet: Wallet):
        """Balance 500, threshold 100, charge 50 → balance 450, no reload needed."""
        await wallet.create("agent-ok", initial_balance=500.0, signup_bonus=False)
        await wallet.enable_auto_reload("agent-ok", threshold=100.0, reload_amount=1000.0)

        new_balance = await wallet.charge("agent-ok", 50.0, "api call")
        assert new_balance == 450.0  # No reload triggered

    async def test_charge_no_reload_when_disabled(self, wallet: Wallet):
        """Auto-reload disabled, balance drops below threshold but no reload."""
        await wallet.create("agent-nd", initial_balance=200.0, signup_bonus=False)
        new_balance = await wallet.charge("agent-nd", 150.0, "api call")
        assert new_balance == 50.0  # No auto-reload, just the debit


class TestAutoReloadOnWithdraw:
    """Auto-reload should also trigger on withdraw."""

    async def test_withdraw_triggers_reload(self, wallet: Wallet):
        await wallet.create("agent-wd", initial_balance=200.0, signup_bonus=False)
        await wallet.enable_auto_reload("agent-wd", threshold=100.0, reload_amount=500.0)

        new_balance = await wallet.withdraw("agent-wd", 150.0, "payout")
        # 200 - 150 = 50 < 100 → reload 500 → 550
        assert new_balance == 550.0


class TestAutoReloadEvents:
    """Verify events and transactions for auto-reload."""

    async def test_reload_emits_event(self, wallet: Wallet, storage):
        await wallet.create("agent-ev", initial_balance=200.0, signup_bonus=False)
        await wallet.enable_auto_reload("agent-ev", threshold=100.0, reload_amount=1000.0)
        await wallet.charge("agent-ev", 150.0, "trigger reload")

        events = await storage.get_pending_events(limit=20)
        reload_events = [e for e in events if e["event_type"] == "wallet.auto_reload"]
        assert len(reload_events) == 1

    async def test_reload_records_transaction(self, wallet: Wallet, storage):
        await wallet.create("agent-tx", initial_balance=200.0, signup_bonus=False)
        await wallet.enable_auto_reload("agent-tx", threshold=100.0, reload_amount=1000.0)
        await wallet.charge("agent-tx", 150.0, "trigger reload")

        txns = await storage.get_transactions("agent-tx")
        reload_txns = [t for t in txns if t["tx_type"] == "auto_reload"]
        assert len(reload_txns) == 1
        assert reload_txns[0]["amount"] == 1000.0
