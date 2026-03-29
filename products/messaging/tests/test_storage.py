"""Tests for messaging storage layer — CRUD for messages and negotiations."""

from __future__ import annotations

import time

from products.messaging.src.models import Message, MessageType, NegotiationState

# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------


class TestStoreMessage:
    async def test_store_and_retrieve(self, storage):
        msg = Message(
            sender="agent-a",
            recipient="agent-b",
            message_type=MessageType.TEXT,
            subject="Hello",
            body="World",
        )
        msg_id = await storage.store_message(msg)
        assert msg_id == msg.id

        # Retrieve by recipient
        msgs = await storage.get_messages("agent-b")
        assert len(msgs) == 1
        assert msgs[0]["id"] == msg_id
        assert msgs[0]["sender"] == "agent-a"
        assert msgs[0]["recipient"] == "agent-b"
        assert msgs[0]["message_type"] == "text"
        assert msgs[0]["subject"] == "Hello"
        assert msgs[0]["body"] == "World"

    async def test_store_message_with_metadata(self, storage):
        msg = Message(
            sender="agent-a",
            recipient="agent-b",
            message_type=MessageType.TASK_SPECIFICATION,
            metadata={"task": "summarize", "priority": 5},
        )
        await storage.store_message(msg)

        msgs = await storage.get_messages("agent-b")
        assert msgs[0]["metadata"] == {"task": "summarize", "priority": 5}

    async def test_get_messages_returns_sender_and_recipient(self, storage):
        """get_messages(agent_id) returns messages where agent is sender OR recipient."""
        msg1 = Message(sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT)
        msg2 = Message(sender="agent-b", recipient="agent-a", message_type=MessageType.TEXT)
        msg3 = Message(sender="agent-c", recipient="agent-d", message_type=MessageType.TEXT)
        await storage.store_message(msg1)
        await storage.store_message(msg2)
        await storage.store_message(msg3)

        msgs_a = await storage.get_messages("agent-a")
        assert len(msgs_a) == 2
        ids = {m["id"] for m in msgs_a}
        assert msg1.id in ids
        assert msg2.id in ids

    async def test_get_messages_limit(self, storage):
        for i in range(10):
            msg = Message(sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT, body=str(i))
            await storage.store_message(msg)

        msgs = await storage.get_messages("agent-a", limit=3)
        assert len(msgs) == 3

    async def test_get_messages_ordered_newest_first(self, storage):
        msg1 = Message(
            sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT, body="first", created_at=1000.0
        )
        msg2 = Message(
            sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT, body="second", created_at=2000.0
        )
        await storage.store_message(msg1)
        await storage.store_message(msg2)

        msgs = await storage.get_messages("agent-a")
        assert msgs[0]["body"] == "second"
        assert msgs[1]["body"] == "first"


class TestGetThread:
    async def test_get_thread(self, storage):
        thread = "thread-123"
        msg1 = Message(
            sender="a", recipient="b", message_type=MessageType.TEXT, thread_id=thread, body="msg1", created_at=1000.0
        )
        msg2 = Message(
            sender="b", recipient="a", message_type=MessageType.TEXT, thread_id=thread, body="msg2", created_at=2000.0
        )
        msg3 = Message(sender="a", recipient="c", message_type=MessageType.TEXT, thread_id="other", body="msg3")
        await storage.store_message(msg1)
        await storage.store_message(msg2)
        await storage.store_message(msg3)

        thread_msgs = await storage.get_thread(thread)
        assert len(thread_msgs) == 2
        # Ordered by created_at ascending (oldest first in thread)
        assert thread_msgs[0]["body"] == "msg1"
        assert thread_msgs[1]["body"] == "msg2"

    async def test_get_thread_empty(self, storage):
        result = await storage.get_thread("nonexistent")
        assert result == []


class TestMarkRead:
    async def test_mark_read_sets_timestamp(self, storage):
        msg = Message(sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT)
        await storage.store_message(msg)

        before = time.time()
        result = await storage.mark_read(msg.id, "agent-b")
        after = time.time()
        assert result is True

        msgs = await storage.get_messages("agent-b")
        assert msgs[0]["read_at"] is not None
        assert before <= msgs[0]["read_at"] <= after

    async def test_mark_read_wrong_agent(self, storage):
        """Only the recipient can mark a message as read."""
        msg = Message(sender="agent-a", recipient="agent-b", message_type=MessageType.TEXT)
        await storage.store_message(msg)

        result = await storage.mark_read(msg.id, "agent-c")
        assert result is False

    async def test_mark_read_nonexistent_message(self, storage):
        result = await storage.mark_read("nonexistent-id", "agent-a")
        assert result is False


# ---------------------------------------------------------------------------
# Negotiation CRUD
# ---------------------------------------------------------------------------


class TestNegotiationStorage:
    async def test_store_and_retrieve_negotiation(self, storage):
        data = {
            "thread_id": "thread-neg-1",
            "initiator": "agent-a",
            "responder": "agent-b",
            "proposed_amount": 100.0,
            "current_amount": 100.0,
            "status": NegotiationState.PROPOSED.value,
            "service_id": "svc-translate",
            "expires_at": time.time() + 86400,
        }
        neg_id = await storage.store_negotiation(data)
        assert neg_id is not None

        neg = await storage.get_negotiation(neg_id)
        assert neg is not None
        assert neg["initiator"] == "agent-a"
        assert neg["responder"] == "agent-b"
        assert neg["proposed_amount"] == 100.0
        assert neg["current_amount"] == 100.0
        assert neg["status"] == "proposed"
        assert neg["service_id"] == "svc-translate"

    async def test_get_negotiation_nonexistent(self, storage):
        result = await storage.get_negotiation("nonexistent-id")
        assert result is None

    async def test_update_negotiation(self, storage):
        data = {
            "thread_id": "thread-neg-2",
            "initiator": "agent-a",
            "responder": "agent-b",
            "proposed_amount": 200.0,
            "current_amount": 200.0,
            "status": NegotiationState.PROPOSED.value,
            "service_id": "svc-code-review",
            "expires_at": time.time() + 86400,
        }
        neg_id = await storage.store_negotiation(data)

        await storage.update_negotiation(
            neg_id,
            {
                "current_amount": 150.0,
                "status": NegotiationState.COUNTERED.value,
            },
        )

        neg = await storage.get_negotiation(neg_id)
        assert neg["current_amount"] == 150.0
        assert neg["status"] == "countered"
        # updated_at should be set
        assert neg["updated_at"] is not None
        assert neg["updated_at"] >= neg["created_at"]

    async def test_update_negotiation_preserves_other_fields(self, storage):
        data = {
            "thread_id": "thread-neg-3",
            "initiator": "agent-x",
            "responder": "agent-y",
            "proposed_amount": 500.0,
            "current_amount": 500.0,
            "status": NegotiationState.PROPOSED.value,
            "service_id": "svc-deploy",
            "expires_at": time.time() + 86400,
        }
        neg_id = await storage.store_negotiation(data)

        await storage.update_negotiation(neg_id, {"status": NegotiationState.ACCEPTED.value})

        neg = await storage.get_negotiation(neg_id)
        assert neg["initiator"] == "agent-x"
        assert neg["proposed_amount"] == 500.0
        assert neg["current_amount"] == 500.0
        assert neg["status"] == "accepted"
