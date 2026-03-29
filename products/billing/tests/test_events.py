"""Tests for the billing event stream."""

from __future__ import annotations

from src.events import BillingEventStream


class TestEventEmit:
    async def test_emit_persists_event(self, event_stream: BillingEventStream):
        eid = await event_stream.emit("test.event", "agent-1", {"foo": "bar"})
        assert eid > 0

    async def test_emit_dispatches_to_handler(self, event_stream: BillingEventStream):
        received = []

        @event_stream.on_event
        async def handler(event):
            received.append(event)

        await event_stream.emit("test.event", "agent-1", {"x": 1})
        assert len(received) == 1
        assert received[0]["event_type"] == "test.event"
        assert received[0]["payload"] == {"x": 1}

    async def test_emit_marks_delivered_on_success(self, event_stream: BillingEventStream):
        @event_stream.on_event
        async def handler(event):
            pass  # success

        await event_stream.emit("test.event", "agent-1", {"x": 1})
        pending = await event_stream.get_pending()
        assert len(pending) == 0

    async def test_emit_keeps_pending_on_handler_failure(self, event_stream: BillingEventStream):
        @event_stream.on_event
        async def bad_handler(event):
            raise RuntimeError("handler failed")

        await event_stream.emit("test.event", "agent-1", {"x": 1})
        pending = await event_stream.get_pending()
        assert len(pending) == 1

    async def test_multiple_handlers(self, event_stream: BillingEventStream):
        results = {"a": False, "b": False}

        @event_stream.on_event
        async def handler_a(event):
            results["a"] = True

        @event_stream.on_event
        async def handler_b(event):
            results["b"] = True

        await event_stream.emit("test.event", "agent-1", {})
        assert results["a"] is True
        assert results["b"] is True


class TestEventPullBased:
    async def test_get_pending(self, event_stream: BillingEventStream):
        await event_stream.emit("e1", "agent-1", {"a": 1})
        await event_stream.emit("e2", "agent-1", {"b": 2})
        pending = await event_stream.get_pending()
        assert len(pending) == 2

    async def test_acknowledge(self, event_stream: BillingEventStream):
        eid = await event_stream.emit("e1", "agent-1", {"a": 1})
        await event_stream.acknowledge(eid)
        pending = await event_stream.get_pending()
        assert len(pending) == 0


class TestEventQuery:
    async def test_get_events_by_agent(self, event_stream: BillingEventStream):
        await event_stream.emit("e1", "agent-1", {"a": 1})
        await event_stream.emit("e2", "agent-2", {"b": 2})
        events = await event_stream.get_events("agent-1")
        assert len(events) == 1
        assert events[0]["event_type"] == "e1"

    async def test_get_events_empty(self, event_stream: BillingEventStream):
        events = await event_stream.get_events("nobody")
        assert events == []


class TestEventReplay:
    async def test_replay_sends_to_handlers(self, event_stream: BillingEventStream):
        await event_stream.emit("e1", "agent-1", {"a": 1})
        await event_stream.emit("e2", "agent-1", {"b": 2})

        replayed = []

        @event_stream.on_event
        async def handler(event):
            replayed.append(event["event_type"])

        await event_stream.replay("agent-1")
        assert "e1" in replayed
        assert "e2" in replayed


class TestRemoveHandler:
    async def test_remove_handler(self, event_stream: BillingEventStream):
        received = []

        async def handler(event):
            received.append(event)

        event_stream.on_event(handler)
        await event_stream.emit("e1", "agent-1", {})
        assert len(received) == 1

        event_stream.remove_handler(handler)
        await event_stream.emit("e2", "agent-1", {})
        assert len(received) == 1  # no new events
