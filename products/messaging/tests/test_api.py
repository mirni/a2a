"""Tests for MessagingAPI — send_message, get_messages, negotiate flow."""

from __future__ import annotations

import time

import pytest

from products.messaging.src.models import MessageType, NegotiationState


# ---------------------------------------------------------------------------
# send_message / get_messages
# ---------------------------------------------------------------------------


class TestSendMessage:
    async def test_send_text_message(self, api):
        msg = await api.send_message(
            sender="agent-a",
            recipient="agent-b",
            message_type=MessageType.TEXT,
            subject="Greetings",
            body="Hello agent-b",
        )
        assert msg.sender == "agent-a"
        assert msg.recipient == "agent-b"
        assert msg.message_type == MessageType.TEXT
        assert msg.subject == "Greetings"
        assert msg.body == "Hello agent-b"
        assert msg.id is not None

    async def test_send_message_persists(self, api):
        await api.send_message(
            sender="agent-a",
            recipient="agent-b",
            message_type=MessageType.TASK_SPECIFICATION,
            body="Please summarize document X",
            metadata={"doc_id": "X"},
        )
        msgs = await api.get_messages("agent-b")
        assert len(msgs) == 1
        assert msgs[0]["body"] == "Please summarize document X"
        assert msgs[0]["metadata"]["doc_id"] == "X"

    async def test_send_message_with_thread(self, api):
        msg1 = await api.send_message(
            sender="agent-a",
            recipient="agent-b",
            message_type=MessageType.TEXT,
            body="First",
            thread_id="thread-abc",
        )
        msg2 = await api.send_message(
            sender="agent-b",
            recipient="agent-a",
            message_type=MessageType.TEXT,
            body="Reply",
            thread_id="thread-abc",
        )
        thread = await api.get_thread("thread-abc")
        assert len(thread) == 2
        assert thread[0]["body"] == "First"
        assert thread[1]["body"] == "Reply"

    async def test_send_message_default_metadata(self, api):
        msg = await api.send_message(
            sender="a",
            recipient="b",
            message_type=MessageType.TEXT,
        )
        assert msg.metadata == {}


class TestGetMessages:
    async def test_get_messages_limit(self, api):
        for i in range(5):
            await api.send_message(sender="a", recipient="b", message_type=MessageType.TEXT, body=str(i))
        msgs = await api.get_messages("b", limit=2)
        assert len(msgs) == 2

    async def test_get_messages_by_thread(self, api):
        await api.send_message(sender="a", recipient="b", message_type=MessageType.TEXT, thread_id="t1", body="in-thread")
        await api.send_message(sender="a", recipient="b", message_type=MessageType.TEXT, body="no-thread")

        msgs = await api.get_messages("b", thread_id="t1")
        assert len(msgs) == 1
        assert msgs[0]["body"] == "in-thread"


# ---------------------------------------------------------------------------
# Negotiation flow: propose -> counter -> accept
# ---------------------------------------------------------------------------


class TestNegotiatePrice:
    async def test_propose_creates_negotiation(self, api):
        result = await api.negotiate_price(
            initiator="agent-a",
            responder="agent-b",
            amount=100.0,
            service_id="svc-translate",
        )
        assert result["status"] == NegotiationState.PROPOSED.value
        assert result["proposed_amount"] == 100.0
        assert result["current_amount"] == 100.0
        assert result["initiator"] == "agent-a"
        assert result["responder"] == "agent-b"
        assert result["service_id"] == "svc-translate"
        assert "id" in result
        assert "thread_id" in result

    async def test_propose_sends_message(self, api):
        result = await api.negotiate_price(
            initiator="agent-a",
            responder="agent-b",
            amount=50.0,
        )
        # A PRICE_NEGOTIATION message should exist in the thread
        thread = await api.get_thread(result["thread_id"])
        assert len(thread) == 1
        assert thread[0]["message_type"] == MessageType.PRICE_NEGOTIATION.value
        assert thread[0]["sender"] == "agent-a"
        assert thread[0]["recipient"] == "agent-b"

    async def test_counter_offer(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)
        neg_id = neg["id"]

        countered = await api.counter_offer(neg_id, "b", 80.0)
        assert countered["status"] == NegotiationState.COUNTERED.value
        assert countered["current_amount"] == 80.0
        assert countered["proposed_amount"] == 100.0  # original preserved

    async def test_counter_offer_sends_message(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        await api.counter_offer(neg["id"], "b", 80.0)

        thread = await api.get_thread(neg["thread_id"])
        assert len(thread) == 2
        counter_msg = thread[1]
        assert counter_msg["message_type"] == MessageType.COUNTER_OFFER.value
        assert counter_msg["sender"] == "b"

    async def test_counter_offer_wrong_party_rejected(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        with pytest.raises(ValueError, match="not a party"):
            await api.counter_offer(neg["id"], "agent-outsider", 80.0)

    async def test_accept_negotiation(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        accepted = await api.accept_negotiation(neg["id"], "b")
        assert accepted["status"] == NegotiationState.ACCEPTED.value

    async def test_accept_sends_message(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        await api.accept_negotiation(neg["id"], "b")

        thread = await api.get_thread(neg["thread_id"])
        assert len(thread) == 2
        accept_msg = thread[1]
        assert accept_msg["message_type"] == MessageType.ACCEPT.value
        assert accept_msg["sender"] == "b"

    async def test_accept_wrong_party_rejected(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        with pytest.raises(ValueError, match="not a party"):
            await api.accept_negotiation(neg["id"], "outsider")

    async def test_reject_negotiation(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        rejected = await api.reject_negotiation(neg["id"], "b")
        assert rejected["status"] == NegotiationState.REJECTED.value

    async def test_reject_sends_message(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        await api.reject_negotiation(neg["id"], "b")

        thread = await api.get_thread(neg["thread_id"])
        assert len(thread) == 2
        reject_msg = thread[1]
        assert reject_msg["message_type"] == MessageType.REJECT.value

    async def test_reject_wrong_party_rejected(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)

        with pytest.raises(ValueError, match="not a party"):
            await api.reject_negotiation(neg["id"], "outsider")

    async def test_cannot_counter_accepted_negotiation(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)
        await api.accept_negotiation(neg["id"], "b")

        with pytest.raises(ValueError, match="not open"):
            await api.counter_offer(neg["id"], "a", 90.0)

    async def test_cannot_accept_rejected_negotiation(self, api):
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0)
        await api.reject_negotiation(neg["id"], "b")

        with pytest.raises(ValueError, match="not open"):
            await api.accept_negotiation(neg["id"], "a")

    async def test_full_flow_propose_counter_counter_accept(self, api):
        """Full negotiation: propose 100 -> counter 80 -> counter 90 -> accept 90."""
        neg = await api.negotiate_price(initiator="a", responder="b", amount=100.0, service_id="svc-review")
        neg_id = neg["id"]

        # b counters at 80
        countered1 = await api.counter_offer(neg_id, "b", 80.0)
        assert countered1["current_amount"] == 80.0

        # a counters at 90
        countered2 = await api.counter_offer(neg_id, "a", 90.0)
        assert countered2["current_amount"] == 90.0

        # b accepts
        accepted = await api.accept_negotiation(neg_id, "b")
        assert accepted["status"] == NegotiationState.ACCEPTED.value
        assert accepted["current_amount"] == 90.0

        # Thread should have 4 messages: propose, counter, counter, accept
        thread = await api.get_thread(neg["thread_id"])
        assert len(thread) == 4
        types = [m["message_type"] for m in thread]
        assert types == [
            MessageType.PRICE_NEGOTIATION.value,
            MessageType.COUNTER_OFFER.value,
            MessageType.COUNTER_OFFER.value,
            MessageType.ACCEPT.value,
        ]

    async def test_negotiate_with_expiry(self, api):
        neg = await api.negotiate_price(
            initiator="a",
            responder="b",
            amount=100.0,
            expires_hours=48,
        )
        assert neg["expires_at"] is not None
        # Should expire roughly 48 hours from now
        expected = time.time() + 48 * 3600
        assert abs(neg["expires_at"] - expected) < 5  # within 5 seconds
