"""Tests for payment Pydantic models."""

from __future__ import annotations

import time

import pytest

from payments.models import (
    Escrow,
    EscrowStatus,
    IntentStatus,
    PaymentIntent,
    Settlement,
    Subscription,
    SubscriptionInterval,
    SubscriptionStatus,
)


# ---------------------------------------------------------------------------
# PaymentIntent
# ---------------------------------------------------------------------------

class TestPaymentIntent:

    def test_create_default(self):
        intent = PaymentIntent(payer="a", payee="b", amount=10.0)
        assert intent.payer == "a"
        assert intent.payee == "b"
        assert intent.amount == 10.0
        assert intent.status == IntentStatus.PENDING
        assert intent.id  # auto-generated
        assert intent.created_at > 0
        assert intent.settlement_id is None

    def test_create_with_idempotency_key(self):
        intent = PaymentIntent(
            payer="a", payee="b", amount=5.0, idempotency_key="req-123"
        )
        assert intent.idempotency_key == "req-123"

    def test_create_with_description(self):
        intent = PaymentIntent(
            payer="a", payee="b", amount=5.0, description="test payment"
        )
        assert intent.description == "test payment"

    def test_create_with_metadata(self):
        intent = PaymentIntent(
            payer="a", payee="b", amount=5.0, metadata={"key": "value"}
        )
        assert intent.metadata == {"key": "value"}

    def test_unique_ids(self):
        i1 = PaymentIntent(payer="a", payee="b", amount=1.0)
        i2 = PaymentIntent(payer="a", payee="b", amount=1.0)
        assert i1.id != i2.id

    def test_model_dump(self):
        intent = PaymentIntent(payer="a", payee="b", amount=10.0)
        d = intent.model_dump()
        assert d["payer"] == "a"
        assert d["payee"] == "b"
        assert d["amount"] == 10.0
        assert d["status"] == "pending"

    def test_model_from_dict(self):
        d = {
            "id": "abc",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "settled",
            "created_at": 1000.0,
            "updated_at": 1000.0,
        }
        intent = PaymentIntent(**d)
        assert intent.id == "abc"
        assert intent.status == IntentStatus.SETTLED

    def test_intent_status_values(self):
        assert IntentStatus.PENDING.value == "pending"
        assert IntentStatus.CAPTURED.value == "captured"
        assert IntentStatus.SETTLED.value == "settled"
        assert IntentStatus.VOIDED.value == "voided"


# ---------------------------------------------------------------------------
# Escrow
# ---------------------------------------------------------------------------

class TestEscrow:

    def test_create_default(self):
        escrow = Escrow(payer="a", payee="b", amount=50.0)
        assert escrow.payer == "a"
        assert escrow.payee == "b"
        assert escrow.amount == 50.0
        assert escrow.status == EscrowStatus.HELD
        assert escrow.timeout_at is None

    def test_create_with_timeout(self):
        timeout = time.time() + 3600
        escrow = Escrow(payer="a", payee="b", amount=50.0, timeout_at=timeout)
        assert escrow.timeout_at == timeout

    def test_create_with_metadata(self):
        escrow = Escrow(
            payer="a", payee="b", amount=50.0, metadata={"task": "pipeline"}
        )
        assert escrow.metadata["task"] == "pipeline"

    def test_escrow_status_values(self):
        assert EscrowStatus.HELD.value == "held"
        assert EscrowStatus.RELEASED.value == "released"
        assert EscrowStatus.SETTLED.value == "settled"
        assert EscrowStatus.REFUNDED.value == "refunded"
        assert EscrowStatus.EXPIRED.value == "expired"

    def test_model_dump(self):
        escrow = Escrow(payer="a", payee="b", amount=50.0)
        d = escrow.model_dump()
        assert d["status"] == "held"
        assert d["amount"] == 50.0

    def test_unique_ids(self):
        e1 = Escrow(payer="a", payee="b", amount=1.0)
        e2 = Escrow(payer="a", payee="b", amount=1.0)
        assert e1.id != e2.id


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class TestSettlement:

    def test_create(self):
        s = Settlement(
            payer="a", payee="b", amount=10.0,
            source_type="intent", source_id="xyz",
        )
        assert s.payer == "a"
        assert s.payee == "b"
        assert s.amount == 10.0
        assert s.source_type == "intent"
        assert s.source_id == "xyz"
        assert s.created_at > 0

    def test_create_with_description(self):
        s = Settlement(
            payer="a", payee="b", amount=10.0,
            source_type="escrow", source_id="xyz",
            description="escrow release",
        )
        assert s.description == "escrow release"

    def test_model_dump(self):
        s = Settlement(
            payer="a", payee="b", amount=10.0,
            source_type="subscription", source_id="sub-1",
        )
        d = s.model_dump()
        assert d["source_type"] == "subscription"

    def test_unique_ids(self):
        s1 = Settlement(payer="a", payee="b", amount=1.0, source_type="intent", source_id="x")
        s2 = Settlement(payer="a", payee="b", amount=1.0, source_type="intent", source_id="x")
        assert s1.id != s2.id


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

class TestSubscription:

    def test_create_default(self):
        sub = Subscription(
            payer="a", payee="b", amount=100.0,
            interval=SubscriptionInterval.MONTHLY,
        )
        assert sub.payer == "a"
        assert sub.payee == "b"
        assert sub.amount == 100.0
        assert sub.interval == SubscriptionInterval.MONTHLY
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.charge_count == 0
        assert sub.cancelled_by is None

    def test_create_hourly(self):
        sub = Subscription(
            payer="a", payee="b", amount=1.0,
            interval=SubscriptionInterval.HOURLY,
        )
        assert sub.interval == SubscriptionInterval.HOURLY

    def test_create_daily(self):
        sub = Subscription(
            payer="a", payee="b", amount=10.0,
            interval=SubscriptionInterval.DAILY,
        )
        assert sub.interval == SubscriptionInterval.DAILY

    def test_create_weekly(self):
        sub = Subscription(
            payer="a", payee="b", amount=50.0,
            interval=SubscriptionInterval.WEEKLY,
        )
        assert sub.interval == SubscriptionInterval.WEEKLY

    def test_compute_next_charge_hourly(self):
        sub = Subscription(
            payer="a", payee="b", amount=1.0,
            interval=SubscriptionInterval.HOURLY,
        )
        before = time.time()
        next_charge = sub.compute_next_charge()
        after = time.time()
        # Should be ~1 hour from now
        assert before + 3600 <= next_charge <= after + 3600

    def test_compute_next_charge_daily(self):
        sub = Subscription(
            payer="a", payee="b", amount=10.0,
            interval=SubscriptionInterval.DAILY,
        )
        before = time.time()
        next_charge = sub.compute_next_charge()
        assert before + 86400 <= next_charge <= time.time() + 86400

    def test_compute_next_charge_weekly(self):
        sub = Subscription(
            payer="a", payee="b", amount=50.0,
            interval=SubscriptionInterval.WEEKLY,
        )
        before = time.time()
        next_charge = sub.compute_next_charge()
        assert before + 604800 <= next_charge <= time.time() + 604800

    def test_compute_next_charge_monthly(self):
        sub = Subscription(
            payer="a", payee="b", amount=100.0,
            interval=SubscriptionInterval.MONTHLY,
        )
        before = time.time()
        next_charge = sub.compute_next_charge()
        assert before + 2592000 <= next_charge <= time.time() + 2592000

    def test_subscription_status_values(self):
        assert SubscriptionStatus.ACTIVE.value == "active"
        assert SubscriptionStatus.CANCELLED.value == "cancelled"
        assert SubscriptionStatus.SUSPENDED.value == "suspended"

    def test_subscription_interval_values(self):
        assert SubscriptionInterval.HOURLY.value == "hourly"
        assert SubscriptionInterval.DAILY.value == "daily"
        assert SubscriptionInterval.WEEKLY.value == "weekly"
        assert SubscriptionInterval.MONTHLY.value == "monthly"

    def test_model_dump(self):
        sub = Subscription(
            payer="a", payee="b", amount=100.0,
            interval=SubscriptionInterval.MONTHLY,
            metadata={"plan": "premium"},
        )
        d = sub.model_dump()
        assert d["interval"] == "monthly"
        assert d["status"] == "active"
        assert d["metadata"] == {"plan": "premium"}

    def test_from_dict_with_string_interval(self):
        d = {
            "id": "sub-1",
            "payer": "a",
            "payee": "b",
            "amount": 100.0,
            "interval": "monthly",
            "status": "active",
            "next_charge_at": time.time() + 3600,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        sub = Subscription(**d)
        assert sub.interval == SubscriptionInterval.MONTHLY
