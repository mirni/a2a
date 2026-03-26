"""Tests for PaymentEngine — the orchestration layer."""

from __future__ import annotations

import time

import pytest

from payments.engine import (
    EscrowNotFoundError,
    IntentNotFoundError,
    InvalidStateError,
    PaymentEngine,
    PaymentError,
    SubscriptionNotFoundError,
)
from payments.models import (
    EscrowStatus,
    IntentStatus,
    SubscriptionStatus,
)

from src.wallet import InsufficientCreditsError


# ---------------------------------------------------------------------------
# Payment Intent lifecycle
# ---------------------------------------------------------------------------

class TestIntentLifecycle:

    async def test_create_intent(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            description="test payment",
        )
        assert intent.payer == "agent-a"
        assert intent.payee == "agent-b"
        assert intent.amount == 10.0
        assert intent.status == IntentStatus.PENDING

    async def test_create_intent_with_metadata(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=5.0,
            metadata={"service": "data-query"},
        )
        assert intent.metadata == {"service": "data-query"}

    async def test_capture_intent(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        settlement = await engine.capture(intent.id)
        assert settlement.amount == 10.0
        assert settlement.source_type == "intent"
        assert settlement.source_id == intent.id

        # Verify balances
        assert await wallet.get_balance("agent-a") == 990.0
        assert await wallet.get_balance("agent-b") == 510.0

    async def test_capture_updates_intent_status(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.capture(intent.id)
        updated = await engine.get_intent(intent.id)
        assert updated.status == IntentStatus.SETTLED
        assert updated.settlement_id is not None

    async def test_void_intent(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        voided = await engine.void(intent.id)
        assert voided.status == IntentStatus.VOIDED

        # Balances unchanged
        assert await wallet.get_balance("agent-a") == 1000.0
        assert await wallet.get_balance("agent-b") == 500.0

    async def test_create_then_void_then_capture_fails(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.void(intent.id)
        with pytest.raises(InvalidStateError, match="voided"):
            await engine.capture(intent.id)

    async def test_double_capture_prevention(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.capture(intent.id)
        with pytest.raises(InvalidStateError, match="settled"):
            await engine.capture(intent.id)

    async def test_double_void_prevention(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.void(intent.id)
        with pytest.raises(InvalidStateError, match="voided"):
            await engine.void(intent.id)

    async def test_capture_nonexistent(self, engine, funded_wallets):
        with pytest.raises(IntentNotFoundError):
            await engine.capture("nonexistent")

    async def test_void_nonexistent(self, engine, funded_wallets):
        with pytest.raises(IntentNotFoundError):
            await engine.void("nonexistent")

    async def test_get_intent(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        fetched = await engine.get_intent(intent.id)
        assert fetched.id == intent.id
        assert fetched.amount == 10.0

    async def test_get_intent_nonexistent(self, engine, funded_wallets):
        with pytest.raises(IntentNotFoundError):
            await engine.get_intent("nonexistent")

    async def test_capture_insufficient_balance(self, engine, funded_wallets):
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=5000.0,
        )
        with pytest.raises(InsufficientCreditsError):
            await engine.capture(intent.id)

    async def test_negative_amount_rejected(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="positive"):
            await engine.create_intent(
                payer="agent-a", payee="agent-b", amount=-10.0,
            )

    async def test_zero_amount_rejected(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="positive"):
            await engine.create_intent(
                payer="agent-a", payee="agent-b", amount=0.0,
            )

    async def test_same_payer_payee_rejected(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="different"):
            await engine.create_intent(
                payer="agent-a", payee="agent-a", amount=10.0,
            )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:

    async def test_idempotency_key_deduplication(self, engine, funded_wallets):
        intent1 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="req-123",
        )
        intent2 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="req-123",
        )
        assert intent1.id == intent2.id

    async def test_idempotency_returns_existing(self, engine, funded_wallets):
        intent1 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="req-456",
            description="first call",
        )
        # Second call with same key but different description
        intent2 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=20.0,
            idempotency_key="req-456",
            description="second call",
        )
        # Should return the first intent unchanged
        assert intent2.id == intent1.id
        assert intent2.amount == 10.0
        assert intent2.description == "first call"

    async def test_different_idempotency_keys_create_separate(self, engine, funded_wallets):
        intent1 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="key-a",
        )
        intent2 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="key-b",
        )
        assert intent1.id != intent2.id

    async def test_no_idempotency_key_always_creates(self, engine, funded_wallets):
        intent1 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        intent2 = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        assert intent1.id != intent2.id

    async def test_idempotency_after_capture(self, engine, funded_wallets):
        """Idempotency key should still return the intent even after capture."""
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="cap-key",
        )
        await engine.capture(intent.id)
        # Re-create with same key should return the settled intent
        dup = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
            idempotency_key="cap-key",
        )
        assert dup.id == intent.id
        assert dup.status == IntentStatus.SETTLED


# ---------------------------------------------------------------------------
# Escrow lifecycle
# ---------------------------------------------------------------------------

class TestEscrowLifecycle:

    async def test_create_escrow(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
            description="pipeline build",
        )
        assert escrow.status == EscrowStatus.HELD
        assert escrow.amount == 100.0
        # Funds withdrawn from payer
        assert await wallet.get_balance("agent-a") == 900.0

    async def test_create_escrow_with_timeout(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
            timeout_hours=24,
        )
        assert escrow.timeout_at is not None
        assert escrow.timeout_at > time.time()

    async def test_release_escrow(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        settlement = await engine.release_escrow(escrow.id)
        assert settlement.amount == 100.0
        assert settlement.source_type == "escrow"
        # Payee receives funds
        assert await wallet.get_balance("agent-b") == 600.0
        # Payer balance unchanged after release (already deducted at hold)
        assert await wallet.get_balance("agent-a") == 900.0

    async def test_release_escrow_updates_status(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        await engine.release_escrow(escrow.id)
        updated = await engine.get_escrow(escrow.id)
        assert updated.status == EscrowStatus.SETTLED

    async def test_refund_escrow(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        refunded = await engine.refund_escrow(escrow.id)
        assert refunded.status == EscrowStatus.REFUNDED
        # Payer gets funds back
        assert await wallet.get_balance("agent-a") == 1000.0
        # Payee unchanged
        assert await wallet.get_balance("agent-b") == 500.0

    async def test_expire_escrow(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
            timeout_hours=0.001,  # very short timeout
        )
        expired = await engine.expire_escrow(escrow.id)
        assert expired.status == EscrowStatus.EXPIRED
        # Payer gets funds back
        assert await wallet.get_balance("agent-a") == 1000.0

    async def test_double_release_prevention(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        await engine.release_escrow(escrow.id)
        with pytest.raises(InvalidStateError, match="settled"):
            await engine.release_escrow(escrow.id)

    async def test_refund_after_release_fails(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        await engine.release_escrow(escrow.id)
        with pytest.raises(InvalidStateError, match="settled"):
            await engine.refund_escrow(escrow.id)

    async def test_release_after_refund_fails(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=100.0,
        )
        await engine.refund_escrow(escrow.id)
        with pytest.raises(InvalidStateError, match="refunded"):
            await engine.release_escrow(escrow.id)

    async def test_expire_after_refund_fails(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
        )
        await engine.refund_escrow(escrow.id)
        with pytest.raises(InvalidStateError, match="refunded"):
            await engine.expire_escrow(escrow.id)

    async def test_release_nonexistent(self, engine, funded_wallets):
        with pytest.raises(EscrowNotFoundError):
            await engine.release_escrow("nonexistent")

    async def test_refund_nonexistent(self, engine, funded_wallets):
        with pytest.raises(EscrowNotFoundError):
            await engine.refund_escrow("nonexistent")

    async def test_get_escrow(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
        )
        fetched = await engine.get_escrow(escrow.id)
        assert fetched.id == escrow.id

    async def test_get_escrow_nonexistent(self, engine, funded_wallets):
        with pytest.raises(EscrowNotFoundError):
            await engine.get_escrow("nonexistent")

    async def test_escrow_insufficient_balance(self, engine, funded_wallets):
        with pytest.raises(InsufficientCreditsError):
            await engine.create_escrow(
                payer="agent-a", payee="agent-b", amount=5000.0,
            )

    async def test_escrow_negative_amount(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="positive"):
            await engine.create_escrow(
                payer="agent-a", payee="agent-b", amount=-10.0,
            )

    async def test_escrow_same_payer_payee(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="different"):
            await engine.create_escrow(
                payer="agent-a", payee="agent-a", amount=10.0,
            )

    async def test_escrow_negative_timeout(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="positive"):
            await engine.create_escrow(
                payer="agent-a", payee="agent-b", amount=10.0,
                timeout_hours=-1,
            )

    async def test_process_expired_escrows(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        # Create escrow with already-expired timeout
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
            timeout_hours=0.0001,  # ~0.36 seconds
        )
        # Wait briefly to ensure timeout passes
        import asyncio
        await asyncio.sleep(0.5)
        expired = await engine.process_expired_escrows()
        assert len(expired) == 1
        assert expired[0].status == EscrowStatus.EXPIRED
        # Payer refunded
        assert await wallet.get_balance("agent-a") == 1000.0

    async def test_process_expired_escrows_empty(self, engine, funded_wallets):
        expired = await engine.process_expired_escrows()
        assert expired == []

    async def test_escrow_with_metadata(self, engine, funded_wallets):
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
            metadata={"task_id": "build-123"},
        )
        assert escrow.metadata == {"task_id": "build-123"}


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------

class TestSubscriptionLifecycle:

    async def test_create_subscription(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=100.0,
            interval="monthly", description="premium feed",
        )
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.amount == 100.0
        assert sub.charge_count == 0
        assert sub.next_charge_at > time.time()

    async def test_create_subscription_hourly(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=1.0,
            interval="hourly",
        )
        assert sub.next_charge_at < time.time() + 3700

    async def test_create_subscription_daily(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="daily",
        )
        assert sub.next_charge_at < time.time() + 86500

    async def test_create_subscription_weekly(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=50.0,
            interval="weekly",
        )
        assert sub.next_charge_at > time.time()

    async def test_create_subscription_invalid_interval(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="Invalid interval"):
            await engine.create_subscription(
                payer="agent-a", payee="agent-b", amount=10.0,
                interval="biweekly",
            )

    async def test_cancel_subscription(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=100.0,
            interval="monthly",
        )
        cancelled = await engine.cancel_subscription(sub.id, cancelled_by="agent-a")
        assert cancelled.status == SubscriptionStatus.CANCELLED
        assert cancelled.cancelled_by == "agent-a"

    async def test_cancel_subscription_by_payee(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=100.0,
            interval="monthly",
        )
        cancelled = await engine.cancel_subscription(sub.id, cancelled_by="agent-b")
        assert cancelled.cancelled_by == "agent-b"

    async def test_cancel_already_cancelled(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=100.0,
            interval="monthly",
        )
        await engine.cancel_subscription(sub.id)
        with pytest.raises(InvalidStateError, match="cancelled"):
            await engine.cancel_subscription(sub.id)

    async def test_cancel_nonexistent(self, engine, funded_wallets):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.cancel_subscription("nonexistent")

    async def test_charge_subscription(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=50.0,
            interval="monthly",
        )
        # Manually set next_charge to past so we can charge
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        settlement = await engine.charge_subscription(sub.id)
        assert settlement.amount == 50.0
        assert settlement.source_type == "subscription"
        assert await wallet.get_balance("agent-a") == 950.0
        assert await wallet.get_balance("agent-b") == 550.0

    async def test_charge_subscription_increments_count(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        await engine.charge_subscription(sub.id)
        updated = await engine.get_subscription(sub.id)
        assert updated.charge_count == 1
        assert updated.last_charged_at is not None

    async def test_charge_subscription_updates_next_charge(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        old_next = sub.next_charge_at
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        await engine.charge_subscription(sub.id)
        updated = await engine.get_subscription(sub.id)
        # Next charge should be ~1 hour from now
        assert updated.next_charge_at > time.time()

    async def test_charge_insufficient_balance_suspends(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=5000.0,
            interval="monthly",
        )
        await engine.storage.update_subscription(sub.id, {
            "next_charge_at": time.time() - 100,
        })
        with pytest.raises(InsufficientCreditsError):
            await engine.charge_subscription(sub.id)
        # Should be suspended
        updated = await engine.get_subscription(sub.id)
        assert updated.status == SubscriptionStatus.SUSPENDED

    async def test_charge_cancelled_subscription_fails(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        await engine.cancel_subscription(sub.id)
        with pytest.raises(InvalidStateError, match="cancelled"):
            await engine.charge_subscription(sub.id)

    async def test_suspend_subscription(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        suspended = await engine.suspend_subscription(sub.id)
        assert suspended.status == SubscriptionStatus.SUSPENDED

    async def test_suspend_already_suspended(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        await engine.suspend_subscription(sub.id)
        with pytest.raises(InvalidStateError, match="suspended"):
            await engine.suspend_subscription(sub.id)

    async def test_reactivate_subscription(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        await engine.suspend_subscription(sub.id)
        reactivated = await engine.reactivate_subscription(sub.id)
        assert reactivated.status == SubscriptionStatus.ACTIVE

    async def test_reactivate_active_fails(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        with pytest.raises(InvalidStateError, match="active"):
            await engine.reactivate_subscription(sub.id)

    async def test_reactivate_nonexistent(self, engine, funded_wallets):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.reactivate_subscription("nonexistent")

    async def test_cancel_suspended_subscription(self, engine, funded_wallets):
        """Should be able to cancel a suspended subscription."""
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        await engine.suspend_subscription(sub.id)
        cancelled = await engine.cancel_subscription(sub.id, cancelled_by="agent-a")
        assert cancelled.status == SubscriptionStatus.CANCELLED

    async def test_get_subscription(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly",
        )
        fetched = await engine.get_subscription(sub.id)
        assert fetched.id == sub.id

    async def test_get_subscription_nonexistent(self, engine, funded_wallets):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.get_subscription("nonexistent")

    async def test_subscription_negative_amount(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="positive"):
            await engine.create_subscription(
                payer="agent-a", payee="agent-b", amount=-10.0,
                interval="monthly",
            )

    async def test_subscription_same_payer_payee(self, engine, funded_wallets):
        with pytest.raises(PaymentError, match="different"):
            await engine.create_subscription(
                payer="agent-a", payee="agent-a", amount=10.0,
                interval="monthly",
            )

    async def test_subscription_with_metadata(self, engine, funded_wallets):
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="monthly", metadata={"tier": "premium"},
        )
        assert sub.metadata == {"tier": "premium"}

    async def test_multiple_charges(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        sub = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=10.0,
            interval="hourly",
        )
        for i in range(5):
            await engine.storage.update_subscription(sub.id, {
                "next_charge_at": time.time() - 100,
                "status": "active",
            })
            await engine.charge_subscription(sub.id)

        updated = await engine.get_subscription(sub.id)
        assert updated.charge_count == 5
        assert await wallet.get_balance("agent-a") == 950.0
        assert await wallet.get_balance("agent-b") == 550.0


# ---------------------------------------------------------------------------
# Payment History
# ---------------------------------------------------------------------------

class TestPaymentHistory:

    async def test_payment_history_intents(self, engine, funded_wallets):
        await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=20.0,
        )
        history = await engine.get_payment_history("agent-a")
        assert len(history) >= 2

    async def test_payment_history_mixed(self, engine, funded_wallets):
        # Create an intent and capture it
        intent = await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        await engine.capture(intent.id)

        # Create an escrow
        escrow = await engine.create_escrow(
            payer="agent-a", payee="agent-b", amount=50.0,
        )

        history = await engine.get_payment_history("agent-a")
        types = {h["type"] for h in history}
        assert "intent" in types
        assert "settlement" in types
        assert "escrow" in types

    async def test_payment_history_empty(self, engine, funded_wallets):
        history = await engine.get_payment_history("agent-x")
        assert history == []

    async def test_payment_history_pagination(self, engine, funded_wallets):
        for i in range(10):
            await engine.create_intent(
                payer="agent-a", payee="agent-b", amount=1.0,
            )
        history = await engine.get_payment_history("agent-a", limit=3)
        assert len(history) == 3

    async def test_payment_history_both_sides(self, engine, funded_wallets):
        """Both payer and payee should see the transaction."""
        await engine.create_intent(
            payer="agent-a", payee="agent-b", amount=10.0,
        )
        history_a = await engine.get_payment_history("agent-a")
        history_b = await engine.get_payment_history("agent-b")
        assert len(history_a) >= 1
        assert len(history_b) >= 1
