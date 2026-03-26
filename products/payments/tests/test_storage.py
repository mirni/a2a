"""Tests for PaymentStorage CRUD operations."""

from __future__ import annotations

import time

import pytest

from payments.models import (
    EscrowStatus,
    IntentStatus,
    SubscriptionInterval,
    SubscriptionStatus,
)
from payments.storage import PaymentStorage


# ---------------------------------------------------------------------------
# Connection / lifecycle
# ---------------------------------------------------------------------------

class TestStorageLifecycle:

    async def test_connect_and_close(self, payment_db):
        storage = PaymentStorage(dsn=payment_db)
        await storage.connect()
        assert storage._db is not None
        await storage.close()
        assert storage._db is None

    async def test_ensure_connected_raises(self, payment_db):
        storage = PaymentStorage(dsn=payment_db)
        with pytest.raises(RuntimeError, match="not connected"):
            storage._ensure_connected()

    async def test_double_close(self, payment_db):
        storage = PaymentStorage(dsn=payment_db)
        await storage.connect()
        await storage.close()
        await storage.close()  # should not raise

    async def test_db_property(self, payment_storage):
        db = payment_storage.db
        assert db is not None


# ---------------------------------------------------------------------------
# Payment Intents CRUD
# ---------------------------------------------------------------------------

class TestIntentStorage:

    async def test_insert_and_get(self, payment_storage):
        now = time.time()
        data = {
            "id": "intent-1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "description": "test",
            "idempotency_key": "key-1",
            "status": "pending",
            "settlement_id": None,
            "created_at": now,
            "updated_at": now,
            "metadata": {"x": 1},
        }
        await payment_storage.insert_intent(data)
        result = await payment_storage.get_intent("intent-1")
        assert result is not None
        assert result["payer"] == "a"
        assert result["amount"] == 10.0
        assert result["metadata"] == {"x": 1}

    async def test_get_nonexistent(self, payment_storage):
        result = await payment_storage.get_intent("nonexistent")
        assert result is None

    async def test_get_by_idempotency_key(self, payment_storage):
        now = time.time()
        data = {
            "id": "intent-2",
            "payer": "a",
            "payee": "b",
            "amount": 5.0,
            "idempotency_key": "idem-1",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_intent(data)
        result = await payment_storage.get_intent_by_idempotency_key("idem-1")
        assert result is not None
        assert result["id"] == "intent-2"

    async def test_get_by_idempotency_key_nonexistent(self, payment_storage):
        result = await payment_storage.get_intent_by_idempotency_key("nope")
        assert result is None

    async def test_idempotency_key_unique(self, payment_storage):
        now = time.time()
        data1 = {
            "id": "intent-a",
            "payer": "a",
            "payee": "b",
            "amount": 5.0,
            "idempotency_key": "dup-key",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_intent(data1)
        data2 = {**data1, "id": "intent-b"}
        with pytest.raises(Exception):  # IntegrityError
            await payment_storage.insert_intent(data2)

    async def test_null_idempotency_keys_allowed(self, payment_storage):
        """Multiple intents with NULL idempotency_key should be fine."""
        now = time.time()
        for i in range(3):
            data = {
                "id": f"intent-null-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 1.0,
                "idempotency_key": None,
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
            await payment_storage.insert_intent(data)
        results = await payment_storage.list_intents(agent_id="a")
        assert len(results) == 3

    async def test_update_intent_status(self, payment_storage):
        now = time.time()
        data = {
            "id": "intent-upd",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_intent(data)
        await payment_storage.update_intent_status("intent-upd", "settled", settlement_id="stl-1")
        result = await payment_storage.get_intent("intent-upd")
        assert result["status"] == "settled"
        assert result["settlement_id"] == "stl-1"
        assert result["updated_at"] > now

    async def test_update_intent_status_without_settlement(self, payment_storage):
        now = time.time()
        data = {
            "id": "intent-void",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_intent(data)
        await payment_storage.update_intent_status("intent-void", "voided")
        result = await payment_storage.get_intent("intent-void")
        assert result["status"] == "voided"
        assert result["settlement_id"] is None

    async def test_list_intents_by_agent(self, payment_storage):
        now = time.time()
        for i in range(5):
            payer = "a" if i < 3 else "c"
            data = {
                "id": f"li-{i}",
                "payer": payer,
                "payee": "b",
                "amount": 1.0,
                "status": "pending",
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_intent(data)
        # Agent "a" as payer
        results = await payment_storage.list_intents(agent_id="a")
        assert len(results) == 3
        # Agent "b" as payee (all 5)
        results = await payment_storage.list_intents(agent_id="b")
        assert len(results) == 5

    async def test_list_intents_by_status(self, payment_storage):
        now = time.time()
        for i, status in enumerate(["pending", "pending", "settled", "voided"]):
            data = {
                "id": f"ls-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 1.0,
                "status": status,
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_intent(data)
        results = await payment_storage.list_intents(status="pending")
        assert len(results) == 2
        results = await payment_storage.list_intents(status="settled")
        assert len(results) == 1

    async def test_list_intents_limit_offset(self, payment_storage):
        now = time.time()
        for i in range(10):
            data = {
                "id": f"lo-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 1.0,
                "status": "pending",
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_intent(data)
        results = await payment_storage.list_intents(limit=3, offset=0)
        assert len(results) == 3
        results = await payment_storage.list_intents(limit=3, offset=8)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Escrow CRUD
# ---------------------------------------------------------------------------

class TestEscrowStorage:

    async def test_insert_and_get(self, payment_storage):
        now = time.time()
        data = {
            "id": "esc-1",
            "payer": "a",
            "payee": "b",
            "amount": 50.0,
            "description": "pipeline",
            "status": "held",
            "timeout_at": now + 3600,
            "created_at": now,
            "updated_at": now,
            "metadata": {"task": "build"},
        }
        await payment_storage.insert_escrow(data)
        result = await payment_storage.get_escrow("esc-1")
        assert result is not None
        assert result["amount"] == 50.0
        assert result["metadata"] == {"task": "build"}

    async def test_get_nonexistent(self, payment_storage):
        result = await payment_storage.get_escrow("nonexistent")
        assert result is None

    async def test_update_escrow_status(self, payment_storage):
        now = time.time()
        data = {
            "id": "esc-upd",
            "payer": "a",
            "payee": "b",
            "amount": 50.0,
            "status": "held",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_escrow(data)
        await payment_storage.update_escrow_status("esc-upd", "settled", settlement_id="stl-e1")
        result = await payment_storage.get_escrow("esc-upd")
        assert result["status"] == "settled"
        assert result["settlement_id"] == "stl-e1"

    async def test_update_escrow_status_no_settlement(self, payment_storage):
        now = time.time()
        data = {
            "id": "esc-ref",
            "payer": "a",
            "payee": "b",
            "amount": 50.0,
            "status": "held",
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_escrow(data)
        await payment_storage.update_escrow_status("esc-ref", "refunded")
        result = await payment_storage.get_escrow("esc-ref")
        assert result["status"] == "refunded"

    async def test_list_escrows_by_agent(self, payment_storage):
        now = time.time()
        for i in range(4):
            data = {
                "id": f"le-{i}",
                "payer": "a" if i < 2 else "c",
                "payee": "b",
                "amount": 10.0,
                "status": "held",
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_escrow(data)
        results = await payment_storage.list_escrows(agent_id="a")
        assert len(results) == 2

    async def test_list_escrows_by_status(self, payment_storage):
        now = time.time()
        for i, status in enumerate(["held", "held", "settled", "refunded"]):
            data = {
                "id": f"les-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 10.0,
                "status": status,
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_escrow(data)
        results = await payment_storage.list_escrows(status="held")
        assert len(results) == 2

    async def test_get_expired_escrows(self, payment_storage):
        now = time.time()
        # Expired escrow (timeout in the past)
        data1 = {
            "id": "exp-1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "held",
            "timeout_at": now - 100,
            "created_at": now - 200,
            "updated_at": now - 200,
        }
        # Not yet expired
        data2 = {
            "id": "exp-2",
            "payer": "a",
            "payee": "b",
            "amount": 20.0,
            "status": "held",
            "timeout_at": now + 3600,
            "created_at": now,
            "updated_at": now,
        }
        # No timeout
        data3 = {
            "id": "exp-3",
            "payer": "a",
            "payee": "b",
            "amount": 30.0,
            "status": "held",
            "timeout_at": None,
            "created_at": now,
            "updated_at": now,
        }
        # Already settled (not eligible)
        data4 = {
            "id": "exp-4",
            "payer": "a",
            "payee": "b",
            "amount": 40.0,
            "status": "settled",
            "timeout_at": now - 100,
            "created_at": now - 200,
            "updated_at": now - 200,
        }
        for d in [data1, data2, data3, data4]:
            await payment_storage.insert_escrow(d)

        expired = await payment_storage.get_expired_escrows(now)
        assert len(expired) == 1
        assert expired[0]["id"] == "exp-1"


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------

class TestSubscriptionStorage:

    async def test_insert_and_get(self, payment_storage):
        now = time.time()
        data = {
            "id": "sub-1",
            "payer": "a",
            "payee": "b",
            "amount": 100.0,
            "interval": "monthly",
            "description": "premium",
            "status": "active",
            "cancelled_by": None,
            "next_charge_at": now + 86400,
            "last_charged_at": None,
            "charge_count": 0,
            "created_at": now,
            "updated_at": now,
            "metadata": {"plan": "gold"},
        }
        await payment_storage.insert_subscription(data)
        result = await payment_storage.get_subscription("sub-1")
        assert result is not None
        assert result["amount"] == 100.0
        assert result["interval"] == "monthly"
        assert result["metadata"] == {"plan": "gold"}

    async def test_get_nonexistent(self, payment_storage):
        result = await payment_storage.get_subscription("nonexistent")
        assert result is None

    async def test_update_subscription(self, payment_storage):
        now = time.time()
        data = {
            "id": "sub-upd",
            "payer": "a",
            "payee": "b",
            "amount": 100.0,
            "interval": "monthly",
            "status": "active",
            "next_charge_at": now + 86400,
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_subscription(data)
        await payment_storage.update_subscription("sub-upd", {
            "status": "cancelled",
            "cancelled_by": "a",
        })
        result = await payment_storage.get_subscription("sub-upd")
        assert result["status"] == "cancelled"
        assert result["cancelled_by"] == "a"
        assert result["updated_at"] > now

    async def test_update_subscription_charge(self, payment_storage):
        now = time.time()
        data = {
            "id": "sub-chg",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "interval": "daily",
            "status": "active",
            "next_charge_at": now,
            "charge_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        await payment_storage.insert_subscription(data)
        await payment_storage.update_subscription("sub-chg", {
            "charge_count": 1,
            "last_charged_at": now,
            "next_charge_at": now + 86400,
        })
        result = await payment_storage.get_subscription("sub-chg")
        assert result["charge_count"] == 1
        assert result["last_charged_at"] == now

    async def test_list_subscriptions_by_agent(self, payment_storage):
        now = time.time()
        for i in range(4):
            data = {
                "id": f"lsub-{i}",
                "payer": "a" if i < 2 else "c",
                "payee": "b",
                "amount": 10.0,
                "interval": "daily",
                "status": "active",
                "next_charge_at": now + 86400,
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_subscription(data)
        results = await payment_storage.list_subscriptions(agent_id="a")
        assert len(results) == 2
        results = await payment_storage.list_subscriptions(agent_id="b")
        assert len(results) == 4

    async def test_list_subscriptions_by_status(self, payment_storage):
        now = time.time()
        for i, status in enumerate(["active", "active", "cancelled", "suspended"]):
            data = {
                "id": f"lss-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 10.0,
                "interval": "daily",
                "status": status,
                "next_charge_at": now + 86400,
                "created_at": now + i,
                "updated_at": now + i,
            }
            await payment_storage.insert_subscription(data)
        results = await payment_storage.list_subscriptions(status="active")
        assert len(results) == 2

    async def test_get_due_subscriptions(self, payment_storage):
        now = time.time()
        # Due subscription
        data1 = {
            "id": "due-1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "interval": "daily",
            "status": "active",
            "next_charge_at": now - 100,
            "created_at": now - 200,
            "updated_at": now - 200,
        }
        # Not yet due
        data2 = {
            "id": "due-2",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "interval": "daily",
            "status": "active",
            "next_charge_at": now + 3600,
            "created_at": now,
            "updated_at": now,
        }
        # Due but cancelled
        data3 = {
            "id": "due-3",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "interval": "daily",
            "status": "cancelled",
            "next_charge_at": now - 100,
            "created_at": now - 200,
            "updated_at": now - 200,
        }
        for d in [data1, data2, data3]:
            await payment_storage.insert_subscription(d)

        due = await payment_storage.get_due_subscriptions(now)
        assert len(due) == 1
        assert due[0]["id"] == "due-1"


# ---------------------------------------------------------------------------
# Settlement CRUD
# ---------------------------------------------------------------------------

class TestSettlementStorage:

    async def test_insert_and_get(self, payment_storage):
        now = time.time()
        data = {
            "id": "stl-1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "source_type": "intent",
            "source_id": "intent-1",
            "description": "test",
            "created_at": now,
        }
        await payment_storage.insert_settlement(data)
        result = await payment_storage.get_settlement("stl-1")
        assert result is not None
        assert result["amount"] == 10.0
        assert result["source_type"] == "intent"

    async def test_get_nonexistent(self, payment_storage):
        result = await payment_storage.get_settlement("nonexistent")
        assert result is None

    async def test_list_settlements(self, payment_storage):
        now = time.time()
        for i in range(5):
            data = {
                "id": f"stl-{i}",
                "payer": "a" if i < 3 else "c",
                "payee": "b",
                "amount": 10.0,
                "source_type": "intent" if i < 2 else "escrow",
                "source_id": f"src-{i}",
                "created_at": now + i,
            }
            await payment_storage.insert_settlement(data)
        # By agent
        results = await payment_storage.list_settlements(agent_id="a")
        assert len(results) == 3
        # By source type
        results = await payment_storage.list_settlements(source_type="intent")
        assert len(results) == 2
        results = await payment_storage.list_settlements(source_type="escrow")
        assert len(results) == 3

    async def test_list_settlements_limit_offset(self, payment_storage):
        now = time.time()
        for i in range(10):
            data = {
                "id": f"stl-lo-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 1.0,
                "source_type": "intent",
                "source_id": f"src-{i}",
                "created_at": now + i,
            }
            await payment_storage.insert_settlement(data)
        results = await payment_storage.list_settlements(limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Payment History
# ---------------------------------------------------------------------------

class TestPaymentHistory:

    async def test_empty_history(self, payment_storage):
        history = await payment_storage.get_payment_history("agent-x")
        assert history == []

    async def test_mixed_history(self, payment_storage):
        now = time.time()
        # Insert intent
        await payment_storage.insert_intent({
            "id": "ph-i1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "settled",
            "created_at": now,
            "updated_at": now,
        })
        # Insert escrow
        await payment_storage.insert_escrow({
            "id": "ph-e1",
            "payer": "a",
            "payee": "b",
            "amount": 50.0,
            "status": "held",
            "created_at": now + 1,
            "updated_at": now + 1,
        })
        # Insert settlement
        await payment_storage.insert_settlement({
            "id": "ph-s1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "source_type": "intent",
            "source_id": "ph-i1",
            "created_at": now + 2,
        })

        history = await payment_storage.get_payment_history("a")
        assert len(history) == 3
        # Should be sorted by created_at descending
        assert history[0]["type"] == "settlement"
        assert history[1]["type"] == "escrow"
        assert history[2]["type"] == "intent"

    async def test_history_pagination(self, payment_storage):
        now = time.time()
        for i in range(5):
            await payment_storage.insert_intent({
                "id": f"php-{i}",
                "payer": "a",
                "payee": "b",
                "amount": 1.0,
                "status": "pending",
                "created_at": now + i,
                "updated_at": now + i,
            })
        history = await payment_storage.get_payment_history("a", limit=2, offset=0)
        assert len(history) == 2
        history = await payment_storage.get_payment_history("a", limit=2, offset=3)
        assert len(history) == 2

    async def test_history_filters_by_agent(self, payment_storage):
        now = time.time()
        await payment_storage.insert_intent({
            "id": "phf-1",
            "payer": "a",
            "payee": "b",
            "amount": 10.0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })
        await payment_storage.insert_intent({
            "id": "phf-2",
            "payer": "c",
            "payee": "d",
            "amount": 10.0,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        })
        history_a = await payment_storage.get_payment_history("a")
        assert len(history_a) == 1
        history_c = await payment_storage.get_payment_history("c")
        assert len(history_c) == 1
        history_x = await payment_storage.get_payment_history("x")
        assert len(history_x) == 0
