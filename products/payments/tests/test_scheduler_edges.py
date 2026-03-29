"""Edge case tests for SubscriptionScheduler.

Covers: no-due subs, insufficient balance, cancelled subs,
simultaneous due, and exact-time boundary.
"""

from __future__ import annotations

import time

from payments.models import SubscriptionStatus


class TestProcessDueEdges:
    async def test_no_due_subscriptions_returns_empty(self, scheduler, funded_wallets):
        """process_due with nothing due should return an empty result, no errors."""
        result = await scheduler.process_due()
        assert result.processed == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.suspended == 0
        assert result.results == []

    async def test_insufficient_balance_handled_gracefully(self, scheduler, engine, billing_wallet):
        """When payer has insufficient balance, process_due should not crash;
        it should record the failure as a suspension."""
        await billing_wallet.create("poor-payer", initial_balance=1.0, signup_bonus=False)
        await billing_wallet.create("payee-x", initial_balance=0.0, signup_bonus=False)

        sub = await engine.create_subscription(
            payer="poor-payer",
            payee="payee-x",
            amount=100.0,
            interval="hourly",
        )
        # Make it due
        await engine.storage.update_subscription(
            sub.id,
            {
                "next_charge_at": time.time() - 10,
            },
        )

        result = await scheduler.process_due()
        assert result.processed == 1
        assert result.succeeded == 0
        assert result.suspended == 1
        assert result.results[0].success is False
        assert "insufficient" in result.results[0].error.lower()

        # Subscription should be suspended
        updated = await engine.get_subscription(sub.id)
        assert updated.status == SubscriptionStatus.SUSPENDED

    async def test_cancelled_subscription_skipped(self, scheduler, engine, funded_wallets):
        """A cancelled subscription with next_charge_at in the past should
        NOT be processed because get_due_subscriptions only queries status='active'."""
        sub = await engine.create_subscription(
            payer="agent-a",
            payee="agent-b",
            amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(
            sub.id,
            {
                "next_charge_at": time.time() - 100,
            },
        )
        await engine.cancel_subscription(sub.id)

        result = await scheduler.process_due()
        assert result.processed == 0

    async def test_multiple_subscriptions_due_simultaneously(self, scheduler, engine, funded_wallets):
        """Multiple subscriptions due at the same instant should all be processed."""
        wallet, _, _ = funded_wallets
        now = time.time()
        sub_ids = []
        for _i in range(5):
            sub = await engine.create_subscription(
                payer="agent-a",
                payee="agent-b",
                amount=10.0,
                interval="hourly",
            )
            await engine.storage.update_subscription(
                sub.id,
                {
                    "next_charge_at": now - 1,  # All due at the same time
                },
            )
            sub_ids.append(sub.id)

        result = await scheduler.process_due()
        assert result.processed == 5
        assert result.succeeded == 5
        assert result.failed == 0

        # Verify funds moved correctly
        assert await wallet.get_balance("agent-a") == 1000.0 - 50.0
        assert await wallet.get_balance("agent-b") == 500.0 + 50.0

    async def test_subscription_due_at_exact_now(self, scheduler, engine, funded_wallets):
        """A subscription with next_charge_at exactly at `now` should be processed
        (the query is next_charge_at <= now)."""
        wallet, _, _ = funded_wallets
        exact_now = time.time()

        sub = await engine.create_subscription(
            payer="agent-a",
            payee="agent-b",
            amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(
            sub.id,
            {
                "next_charge_at": exact_now,
            },
        )

        # Use exact_now as the `now` parameter so <= is satisfied exactly
        result = await scheduler.process_due(now=exact_now)
        assert result.processed == 1
        assert result.succeeded == 1

    async def test_suspended_subscription_not_processed(self, scheduler, engine, funded_wallets):
        """A suspended subscription should not be picked up by get_due_subscriptions."""
        sub = await engine.create_subscription(
            payer="agent-a",
            payee="agent-b",
            amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(
            sub.id,
            {
                "next_charge_at": time.time() - 100,
            },
        )
        await engine.suspend_subscription(sub.id)

        result = await scheduler.process_due()
        assert result.processed == 0

    async def test_next_charge_at_updated_after_success(self, scheduler, engine, funded_wallets):
        """After a successful charge, next_charge_at should be pushed forward."""
        sub = await engine.create_subscription(
            payer="agent-a",
            payee="agent-b",
            amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(
            sub.id,
            {
                "next_charge_at": time.time() - 100,
            },
        )

        await scheduler.process_due()
        updated = await engine.get_subscription(sub.id)
        # next_charge_at should now be in the future
        assert updated.next_charge_at > time.time() - 10
        assert updated.charge_count == 1
