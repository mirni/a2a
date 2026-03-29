"""Tests for the cross-product event bus (TDD — written before implementation)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

import pytest
from src.event_bus import EventBus


@pytest.fixture
async def bus(tmp_path):
    """Create an EventBus backed by a temporary SQLite database."""
    dsn = f"sqlite:///{tmp_path}/events.db"
    eb = EventBus(dsn=dsn)
    await eb.connect()
    yield eb
    await eb.close()


# ---------------------------------------------------------------------------
# Publish + SHA-3 integrity hash
# ---------------------------------------------------------------------------


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_returns_positive_id(self, bus: EventBus):
        event_id = await bus.publish("order.created", "billing", {"amount": 42})
        assert isinstance(event_id, int)
        assert event_id >= 1

    @pytest.mark.asyncio
    async def test_publish_stores_sha3_integrity_hash(self, bus: EventBus):
        await bus.publish("order.created", "billing", {"amount": 42})
        events = await bus.get_events(event_type="order.created")
        assert len(events) == 1
        ev = events[0]
        assert "integrity_hash" in ev
        # The hash must be a valid hex string of SHA-3-256 length (64 hex chars)
        assert len(ev["integrity_hash"]) == 64

    @pytest.mark.asyncio
    async def test_integrity_hash_uses_sha3_256(self, bus: EventBus):
        """Verify the stored hash matches SHA-3-256 recomputation."""
        payload = {"amount": 99, "currency": "USD"}
        await bus.publish("payment.settled", "payments", payload)
        events = await bus.get_events(event_type="payment.settled")
        ev = events[0]

        # Recompute: event_type + source + json(payload) + timestamp
        raw = ev["event_type"] + ev["source"] + json.dumps(ev["payload"], sort_keys=True) + ev["created_at"]
        expected = hashlib.sha3_256(raw.encode()).hexdigest()
        assert ev["integrity_hash"] == expected

    @pytest.mark.asyncio
    async def test_publish_multiple_events_get_sequential_ids(self, bus: EventBus):
        id1 = await bus.publish("a", "src", {})
        id2 = await bus.publish("b", "src", {})
        id3 = await bus.publish("c", "src", {})
        assert id1 < id2 < id3


# ---------------------------------------------------------------------------
# Subscribe + handler invocation
# ---------------------------------------------------------------------------


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_handler_called_on_matching_event(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event)

        await bus.subscribe("order.created", handler)
        await bus.publish("order.created", "billing", {"item": "widget"})
        # Allow async dispatch
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0]["payload"]["item"] == "widget"

    @pytest.mark.asyncio
    async def test_subscribe_handler_not_called_for_other_event_types(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event)

        await bus.subscribe("order.created", handler)
        await bus.publish("payment.settled", "payments", {"id": "p1"})
        await asyncio.sleep(0.05)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_subscribe_returns_subscription_id(self, bus: EventBus):
        async def handler(event: dict):
            pass

        sub_id = await bus.subscribe("x", handler)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event)

        sub_id = await bus.subscribe("order.created", handler)
        await bus.unsubscribe(sub_id)
        await bus.publish("order.created", "billing", {"item": "gone"})
        await asyncio.sleep(0.05)

        assert len(received) == 0


# ---------------------------------------------------------------------------
# Subscribe with filter
# ---------------------------------------------------------------------------


class TestSubscribeWithFilter:
    @pytest.mark.asyncio
    async def test_filter_passes_matching_events(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event)

        def high_value(event: dict) -> bool:
            return event["payload"].get("amount", 0) > 100

        await bus.subscribe("payment.settled", handler, filter_fn=high_value)

        await bus.publish("payment.settled", "payments", {"amount": 200})
        await bus.publish("payment.settled", "payments", {"amount": 50})
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0]["payload"]["amount"] == 200

    @pytest.mark.asyncio
    async def test_filter_blocks_non_matching_events(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event)

        def only_usd(event: dict) -> bool:
            return event["payload"].get("currency") == "USD"

        await bus.subscribe("payment.settled", handler, filter_fn=only_usd)

        await bus.publish("payment.settled", "payments", {"currency": "EUR", "amount": 500})
        await asyncio.sleep(0.05)

        assert len(received) == 0


# ---------------------------------------------------------------------------
# Event replay from offset
# ---------------------------------------------------------------------------


class TestReplay:
    @pytest.mark.asyncio
    async def test_get_events_since_id(self, bus: EventBus):
        id1 = await bus.publish("evt", "src", {"n": 1})
        id2 = await bus.publish("evt", "src", {"n": 2})
        id3 = await bus.publish("evt", "src", {"n": 3})

        events = await bus.get_events(event_type="evt", since_id=id1)
        assert len(events) == 2
        assert events[0]["id"] == id2
        assert events[1]["id"] == id3

    @pytest.mark.asyncio
    async def test_get_events_all_types(self, bus: EventBus):
        await bus.publish("a", "src", {})
        await bus.publish("b", "src", {})
        events = await bus.get_events()
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_get_events_respects_limit(self, bus: EventBus):
        for i in range(10):
            await bus.publish("evt", "src", {"i": i})

        events = await bus.get_events(event_type="evt", limit=3)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_get_events_since_id_zero_returns_all(self, bus: EventBus):
        await bus.publish("evt", "src", {"n": 1})
        await bus.publish("evt", "src", {"n": 2})

        events = await bus.get_events(event_type="evt", since_id=0)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# Event acknowledgment
# ---------------------------------------------------------------------------


class TestAcknowledge:
    @pytest.mark.asyncio
    async def test_acknowledge_updates_last_ack_id(self, bus: EventBus):
        async def handler(event: dict):
            pass

        sub_id = await bus.subscribe("evt", handler)
        eid = await bus.publish("evt", "src", {"n": 1})
        await asyncio.sleep(0.05)

        await bus.acknowledge(sub_id, eid)

        # After ack, the subscription's last_ack_id should be updated
        events = await bus.get_events(event_type="evt", since_id=eid)
        assert len(events) == 0  # no events after the acked one

    @pytest.mark.asyncio
    async def test_acknowledge_allows_replay_from_ack_point(self, bus: EventBus):
        async def handler(event: dict):
            pass

        sub_id = await bus.subscribe("evt", handler)
        await bus.publish("evt", "src", {"n": 1})
        id2 = await bus.publish("evt", "src", {"n": 2})
        id3 = await bus.publish("evt", "src", {"n": 3})
        await asyncio.sleep(0.05)

        await bus.acknowledge(sub_id, id2)

        # Events after the ack point
        events = await bus.get_events(event_type="evt", since_id=id2)
        assert len(events) == 1
        assert events[0]["id"] == id3


# ---------------------------------------------------------------------------
# Multiple subscribers for same event type
# ---------------------------------------------------------------------------


class TestMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_multiple_handlers_all_receive_event(self, bus: EventBus):
        results_a = []
        results_b = []
        results_c = []

        async def handler_a(event: dict):
            results_a.append(event)

        async def handler_b(event: dict):
            results_b.append(event)

        async def handler_c(event: dict):
            results_c.append(event)

        await bus.subscribe("shared.event", handler_a)
        await bus.subscribe("shared.event", handler_b)
        await bus.subscribe("shared.event", handler_c)

        await bus.publish("shared.event", "src", {"data": "hello"})
        await asyncio.sleep(0.05)

        assert len(results_a) == 1
        assert len(results_b) == 1
        assert len(results_c) == 1

    @pytest.mark.asyncio
    async def test_unsubscribing_one_does_not_affect_others(self, bus: EventBus):
        results_a = []
        results_b = []

        async def handler_a(event: dict):
            results_a.append(event)

        async def handler_b(event: dict):
            results_b.append(event)

        sub_a = await bus.subscribe("shared.event", handler_a)
        await bus.subscribe("shared.event", handler_b)

        await bus.unsubscribe(sub_a)
        await bus.publish("shared.event", "src", {"data": "test"})
        await asyncio.sleep(0.05)

        assert len(results_a) == 0
        assert len(results_b) == 1


# ---------------------------------------------------------------------------
# Event ordering (FIFO)
# ---------------------------------------------------------------------------


class TestOrdering:
    @pytest.mark.asyncio
    async def test_events_returned_in_fifo_order(self, bus: EventBus):
        for i in range(5):
            await bus.publish("seq", "src", {"order": i})

        events = await bus.get_events(event_type="seq")
        orders = [e["payload"]["order"] for e in events]
        assert orders == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_handler_receives_events_in_publish_order(self, bus: EventBus):
        received = []

        async def handler(event: dict):
            received.append(event["payload"]["order"])

        await bus.subscribe("seq", handler)

        for i in range(5):
            await bus.publish("seq", "src", {"order": i})
            await asyncio.sleep(0.01)

        await asyncio.sleep(0.05)
        assert received == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Integrity verification (tampered event detection)
# ---------------------------------------------------------------------------


class TestIntegrityVerification:
    @pytest.mark.asyncio
    async def test_verify_valid_event(self, bus: EventBus):
        event_id = await bus.publish("trust.drop", "trust", {"score": 30})
        result = await bus.verify_integrity(event_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_tampered_event_detected(self, bus: EventBus):
        event_id = await bus.publish("trust.drop", "trust", {"score": 30})

        # Tamper with the stored payload directly via SQL
        import aiosqlite

        dsn_path = bus.dsn.replace("sqlite:///", "")
        async with aiosqlite.connect(dsn_path) as db:
            await db.execute(
                "UPDATE events SET payload = ? WHERE id = ?",
                (json.dumps({"score": 999}), event_id),
            )
            await db.commit()

        result = await bus.verify_integrity(event_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_all_published_events_are_valid(self, bus: EventBus):
        ids = []
        for i in range(5):
            eid = await bus.publish("batch", "src", {"i": i})
            ids.append(eid)

        for eid in ids:
            assert await bus.verify_integrity(eid) is True


# ---------------------------------------------------------------------------
# Event expiry / cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_events(self, bus: EventBus):
        import aiosqlite

        # Publish events
        await bus.publish("old", "src", {"data": "stale"})
        await bus.publish("old", "src", {"data": "stale2"})

        # Manually backdate them in the database
        dsn_path = bus.dsn.replace("sqlite:///", "")
        async with aiosqlite.connect(dsn_path) as db:
            old_time = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 7200))
            await db.execute("UPDATE events SET created_at = ?", (old_time,))
            await db.commit()

        # Publish a fresh event
        await bus.publish("new", "src", {"data": "fresh"})

        deleted = await bus.cleanup(older_than_seconds=3600)
        assert deleted == 2

        remaining = await bus.get_events()
        assert len(remaining) == 1
        assert remaining[0]["payload"]["data"] == "fresh"

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_nothing_to_delete(self, bus: EventBus):
        await bus.publish("recent", "src", {"data": "new"})
        deleted = await bus.cleanup(older_than_seconds=3600)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_with_zero_threshold_deletes_all(self, bus: EventBus):
        await bus.publish("a", "src", {})
        await bus.publish("b", "src", {})
        # Events are created "now", wait a tiny bit so they are older than 0s
        await asyncio.sleep(0.05)
        deleted = await bus.cleanup(older_than_seconds=0)
        assert deleted == 2
