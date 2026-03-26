"""Tests for SubscriptionScheduler."""

from __future__ import annotations

import time

import pytest

from payments.engine import PaymentEngine, PaymentError
from payments.models import SubscriptionStatus
from payments.scheduler import SubscriptionScheduler

from src.wallet import InsufficientCreditsError


class TestSchedulerProcessDue:

    async def test_no_due_subscriptions(self, scheduler, funded_wallets):
        result = await scheduler.process_due()
        assert result.processed == 0
        assert result.succeeded == 0
        assert result.failed == 0
        assert result.suspended == 0

    async def test_process_single_due(self, scheduler, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        # Make it due now
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        result = await scheduler.process_due()
        assert result.processed == 1
        assert result.succeeded == 1
        assert result.failed == 0
        assert result.suspended == 0
        assert len(result.results) == 1
        assert result.results[0].success is True
        assert result.results[0].settlement is not None

        # Verify balances
        assert await wallet.get_balance("agent-a") == 990.0
        assert await wallet.get_balance("agent-b") == 510.0

    async def test_process_multiple_due(self, scheduler, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        for i in range(3):
            sub = await engine.create_subscription(
                payer="agent-a", payee="agent-b", amount=10.0,
                interval="hourly",
            )
            await engine.storage.update_subscription(sub.id, {
                "next_charge_at": time.time() - 100,
            })

        result = await scheduler.process_due()
        assert result.processed == 3
        assert result.succeeded == 3
        assert await wallet.get_balance("agent-a") == 970.0
        assert await wallet.get_balance("agent-b") == 530.0

    async def test_process_insufficient_balance_suspends(self, scheduler, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=5000.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        result = await scheduler.process_due()
        assert result.processed == 1
        assert result.succeeded == 0
        assert result.suspended == 1
        assert result.results[0].success is False
        assert "insufficient" in result.results[0].error.lower()

        # Verify subscription is suspended
        updated = await engine.get_subscription(sub.id)
        assert updated.status == SubscriptionStatus.SUSPENDED

    async def test_process_skips_not_due(self, scheduler, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",  # Next charge far in the future
        )
        result = await scheduler.process_due()
        assert result.processed == 0

    async def test_process_skips_cancelled(self, scheduler, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        await engine.cancel_subscription(sub.id)
        result = await scheduler.process_due()
        assert result.processed == 0

    async def test_process_expired_escrows(self, scheduler, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
            timeout_hours=0.0001,  # Very short
        )
        import asyncio
        await asyncio.sleep(0.5)

        result = await scheduler.process_due()
        assert result.expired_escrows == 1
        # Payer refunded
        assert await wallet.get_balance("agent-a") == 1000.0

    async def test_process_mixed_due_and_expired(self, scheduler, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        # Due subscription
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        # Expired escrow
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
            timeout_hours=0.0001,
        )
        import asyncio
        await asyncio.sleep(0.5)

        result = await scheduler.process_due()
        assert result.processed == 1
        assert result.succeeded == 1
        assert result.expired_escrows == 1

    async def test_custom_now_parameter(self, scheduler, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        # Set next_charge to a specific time
        target_time = time.time() + 1000
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": target_time,
        })
        # Process with now = target_time + 1 (should trigger)
        result = await scheduler.process_due(now=target_time + 1)
        assert result.processed == 1
        assert result.succeeded == 1


class TestSchedulerRun:

    async def test_run_with_max_iterations(self, scheduler, funded_wallets):
        """Run the scheduler for exactly 1 iteration."""
        await scheduler.run(interval=0.01, max_iterations=1)
        # Just verify it doesn't hang or crash

    async def test_run_processes_due_subs(self, scheduler, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        await scheduler.run(interval=0.01, max_iterations=1)
        assert await wallet.get_balance("agent-a") == 990.0

    async def test_run_multiple_iterations(self, scheduler, funded_wallets):
        """Run 3 iterations without issues."""
        await scheduler.run(interval=0.01, max_iterations=3)
