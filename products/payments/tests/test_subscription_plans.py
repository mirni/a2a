"""Tests for monthly subscription plans (TDD).

Plans: Starter $29/mo (3500 credits), Pro $199/mo (25000 credits),
Enterprise (custom, not self-service).
"""

from __future__ import annotations

import time

import pytest
from payments.plans import (
    DuplicatePlanSubscriptionError,
    InvalidPlanError,
    NoPlanSubscriptionError,
    PlanManager,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def plan_mgr(engine, billing_wallet):
    """Yield a PlanManager wired to the test engine and wallet."""
    return PlanManager(engine=engine, wallet=billing_wallet)


@pytest.fixture
async def subscriber_wallet(billing_wallet):
    """Create a subscriber agent wallet."""
    await billing_wallet.create("sub-agent", initial_balance=0.0, signup_bonus=False)
    return billing_wallet


class TestSubscribeToPlan:
    """Test creating plan subscriptions."""

    async def test_subscribe_to_starter_plan(self, plan_mgr, subscriber_wallet):
        sub = await plan_mgr.subscribe("sub-agent", "starter_monthly")
        assert sub.metadata["plan_id"] == "starter_monthly"
        assert sub.metadata["credits_per_cycle"] == 3500
        assert sub.interval.value == "monthly"
        assert sub.status.value == "active"
        assert sub.payer == "platform"
        assert sub.payee == "sub-agent"

    async def test_subscribe_to_pro_plan(self, plan_mgr, subscriber_wallet):
        sub = await plan_mgr.subscribe("sub-agent", "pro_monthly")
        assert sub.metadata["plan_id"] == "pro_monthly"
        assert sub.metadata["credits_per_cycle"] == 25000
        assert sub.interval.value == "monthly"

    async def test_subscribe_grants_initial_credits(self, plan_mgr, subscriber_wallet):
        """First subscription immediately grants credits_included."""
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        balance = await subscriber_wallet.get_balance("sub-agent")
        assert balance == 3500.0

    async def test_subscribe_to_invalid_plan(self, plan_mgr, subscriber_wallet):
        with pytest.raises(InvalidPlanError, match="no_such_plan"):
            await plan_mgr.subscribe("sub-agent", "no_such_plan")

    async def test_subscribe_rejects_enterprise_self_service(self, plan_mgr, subscriber_wallet):
        """Enterprise plan is custom-only, cannot self-subscribe."""
        with pytest.raises(InvalidPlanError, match="custom"):
            await plan_mgr.subscribe("sub-agent", "enterprise_annual")

    async def test_subscribe_when_already_subscribed(self, plan_mgr, subscriber_wallet):
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        with pytest.raises(DuplicatePlanSubscriptionError):
            await plan_mgr.subscribe("sub-agent", "pro_monthly")


class TestProcessDuePlans:
    """Test that due plan subscriptions grant credits."""

    async def test_process_due_grants_credits(self, plan_mgr, subscriber_wallet, engine):
        sub = await plan_mgr.subscribe("sub-agent", "starter_monthly")
        # Make it due now
        await engine.storage.update_subscription(
            sub.id, {"next_charge_at": time.time() - 10}
        )

        result = await plan_mgr.process_due()
        assert result.processed == 1
        assert result.succeeded == 1
        # Initial 3500 + renewal 3500 = 7000
        balance = await subscriber_wallet.get_balance("sub-agent")
        assert balance == 7000.0

    async def test_process_due_updates_next_charge(self, plan_mgr, subscriber_wallet, engine):
        sub = await plan_mgr.subscribe("sub-agent", "starter_monthly")
        await engine.storage.update_subscription(
            sub.id, {"next_charge_at": time.time() - 10}
        )

        await plan_mgr.process_due()
        updated = await engine.get_subscription(sub.id)
        # next_charge_at should be pushed ~30 days into the future
        assert updated.next_charge_at > time.time() + 2500000  # ~29 days

    async def test_process_due_records_transaction(self, plan_mgr, subscriber_wallet, engine):
        sub = await plan_mgr.subscribe("sub-agent", "starter_monthly")
        await engine.storage.update_subscription(
            sub.id, {"next_charge_at": time.time() - 10}
        )

        await plan_mgr.process_due()
        txns = await subscriber_wallet.storage.get_transactions("sub-agent")
        plan_txns = [t for t in txns if "Plan starter_monthly" in t.get("description", "")]
        assert len(plan_txns) == 2  # initial + renewal

    async def test_process_due_skips_not_due(self, plan_mgr, subscriber_wallet):
        """Subscription not yet due should not be processed."""
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        result = await plan_mgr.process_due()
        assert result.processed == 0


class TestCancelPlan:
    """Test plan cancellation."""

    async def test_cancel_plan(self, plan_mgr, subscriber_wallet):
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        sub = await plan_mgr.cancel("sub-agent")
        assert sub.status.value == "cancelled"

    async def test_cancel_when_no_plan(self, plan_mgr, subscriber_wallet):
        with pytest.raises(NoPlanSubscriptionError):
            await plan_mgr.cancel("sub-agent")


class TestChangePlan:
    """Test plan changes (upgrade/downgrade)."""

    async def test_upgrade_starter_to_pro(self, plan_mgr, subscriber_wallet):
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        new_sub = await plan_mgr.change_plan("sub-agent", "pro_monthly")
        assert new_sub.metadata["plan_id"] == "pro_monthly"
        assert new_sub.metadata["credits_per_cycle"] == 25000
        # Starter granted 3500, upgrade grants 25000 = total 28500
        balance = await subscriber_wallet.get_balance("sub-agent")
        assert balance == 28500.0

    async def test_change_plan_cancels_old(self, plan_mgr, subscriber_wallet, engine):
        old_sub = await plan_mgr.subscribe("sub-agent", "starter_monthly")
        await plan_mgr.change_plan("sub-agent", "pro_monthly")
        old = await engine.get_subscription(old_sub.id)
        assert old.status.value == "cancelled"


class TestGetActivePlan:
    """Test retrieving active plan info."""

    async def test_get_active_plan(self, plan_mgr, subscriber_wallet):
        await plan_mgr.subscribe("sub-agent", "starter_monthly")
        info = await plan_mgr.get_active_plan("sub-agent")
        assert info is not None
        assert info["plan_id"] == "starter_monthly"
        assert info["credits_per_cycle"] == 3500
        assert info["price_cents"] == 2900
        assert info["tier"] == "starter"

    async def test_get_active_plan_when_none(self, plan_mgr, subscriber_wallet):
        info = await plan_mgr.get_active_plan("sub-agent")
        assert info is None
