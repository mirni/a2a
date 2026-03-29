"""Tests for spending alerts and budget caps (TDD).

Budget caps: daily and monthly spending limits.
Alerts: events emitted when spending reaches threshold (default 80%).
"""

from __future__ import annotations

import pytest
from src.budget import BudgetCapExceededError, BudgetManager
from src.wallet import Wallet

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def budget_mgr(storage) -> BudgetManager:
    return BudgetManager(storage=storage)


class TestSetBudgetCap:
    """Test setting and retrieving budget caps."""

    async def test_set_daily_cap(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-bc", signup_bonus=False)
        await budget_mgr.set_cap("agent-bc", daily_cap=100.0)
        cap = await budget_mgr.get_cap("agent-bc")
        assert cap is not None
        assert cap["daily_cap"] == 100.0
        assert cap["monthly_cap"] is None

    async def test_set_monthly_cap(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-mc", signup_bonus=False)
        await budget_mgr.set_cap("agent-mc", monthly_cap=3000.0)
        cap = await budget_mgr.get_cap("agent-mc")
        assert cap is not None
        assert cap["monthly_cap"] == 3000.0
        assert cap["daily_cap"] is None

    async def test_set_both_caps(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-both", signup_bonus=False)
        await budget_mgr.set_cap("agent-both", daily_cap=100.0, monthly_cap=2000.0)
        cap = await budget_mgr.get_cap("agent-both")
        assert cap["daily_cap"] == 100.0
        assert cap["monthly_cap"] == 2000.0

    async def test_get_cap_when_not_set(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-nocap", signup_bonus=False)
        cap = await budget_mgr.get_cap("agent-nocap")
        assert cap is None

    async def test_update_existing_cap(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-upd", signup_bonus=False)
        await budget_mgr.set_cap("agent-upd", daily_cap=100.0)
        await budget_mgr.set_cap("agent-upd", daily_cap=200.0)
        cap = await budget_mgr.get_cap("agent-upd")
        assert cap["daily_cap"] == 200.0

    async def test_delete_cap(self, budget_mgr, wallet: Wallet):
        await wallet.create("agent-del", signup_bonus=False)
        await budget_mgr.set_cap("agent-del", daily_cap=100.0)
        await budget_mgr.delete_cap("agent-del")
        cap = await budget_mgr.get_cap("agent-del")
        assert cap is None


class TestBudgetCheck:
    """Test budget enforcement on charges."""

    async def test_charge_within_daily_cap(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-ok", initial_balance=500.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-ok", daily_cap=200.0)
        # Simulate some usage
        await storage.record_usage("agent-ok", "tool1", 50.0)
        # Should not raise
        await budget_mgr.check_budget("agent-ok", additional_cost=50.0)

    async def test_charge_exceeds_daily_cap(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-over", initial_balance=500.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-over", daily_cap=100.0)
        await storage.record_usage("agent-over", "tool1", 80.0)
        with pytest.raises(BudgetCapExceededError, match="daily"):
            await budget_mgr.check_budget("agent-over", additional_cost=30.0)

    async def test_charge_exceeds_monthly_cap(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-mover", initial_balance=5000.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-mover", monthly_cap=1000.0)
        # Record usage spread across multiple days (but within current month)
        for _i in range(10):
            await storage.record_usage("agent-mover", "tool1", 90.0)
        with pytest.raises(BudgetCapExceededError, match="monthly"):
            await budget_mgr.check_budget("agent-mover", additional_cost=200.0)

    async def test_no_cap_allows_unlimited(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-free", initial_balance=5000.0, signup_bonus=False)
        await storage.record_usage("agent-free", "tool1", 1000.0)
        # No cap set, should not raise
        await budget_mgr.check_budget("agent-free", additional_cost=1000.0)


class TestSpendingAlerts:
    """Test that spending alert events are emitted at threshold."""

    async def test_alert_emitted_at_threshold(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-alert", initial_balance=500.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-alert", daily_cap=100.0)
        # Record usage at 80% of cap
        await storage.record_usage("agent-alert", "tool1", 79.0)

        # This check pushes past 80% threshold
        await budget_mgr.check_budget("agent-alert", additional_cost=5.0)

        events = await storage.get_pending_events(limit=20)
        alert_events = [e for e in events if e["event_type"] == "budget.alert"]
        assert len(alert_events) >= 1
        assert alert_events[0]["payload"]["cap_type"] == "daily"

    async def test_no_alert_below_threshold(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-low", initial_balance=500.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-low", daily_cap=100.0)
        await storage.record_usage("agent-low", "tool1", 10.0)

        await budget_mgr.check_budget("agent-low", additional_cost=5.0)

        events = await storage.get_pending_events(limit=20)
        alert_events = [e for e in events if e["event_type"] == "budget.alert"]
        assert len(alert_events) == 0

    async def test_custom_alert_threshold(self, budget_mgr, wallet: Wallet, storage):
        await wallet.create("agent-cust", initial_balance=500.0, signup_bonus=False)
        await budget_mgr.set_cap("agent-cust", daily_cap=100.0, alert_threshold=0.5)
        await storage.record_usage("agent-cust", "tool1", 49.0)

        # 49 + 5 = 54 > 50% of 100 → alert
        await budget_mgr.check_budget("agent-cust", additional_cost=5.0)

        events = await storage.get_pending_events(limit=20)
        alert_events = [e for e in events if e["event_type"] == "budget.alert"]
        assert len(alert_events) >= 1
