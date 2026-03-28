"""Tests for negotiation lifecycle via the MessagingAPI (M-13)."""

from __future__ import annotations

import pytest

from products.messaging.src.models import MessageType, NegotiationState


# ---------------------------------------------------------------------------
# Happy-path lifecycle
# ---------------------------------------------------------------------------


class TestNegotiationLifecycle:
    """Full propose → counter → accept flow."""

    async def test_propose_creates_negotiation_and_message(self, api, storage):
        neg = await api.negotiate_price(
            initiator="alice",
            responder="bob",
            amount=100.0,
            service_id="svc-translate",
        )
        assert neg["initiator"] == "alice"
        assert neg["responder"] == "bob"
        assert neg["proposed_amount"] == 100.0
        assert neg["current_amount"] == 100.0
        assert neg["status"] == NegotiationState.PROPOSED.value

        # A proposal message should exist in the thread
        msgs = await storage.get_thread(neg["thread_id"])
        assert len(msgs) == 1
        assert msgs[0]["message_type"] == MessageType.PRICE_NEGOTIATION.value
        assert msgs[0]["sender"] == "alice"
        assert msgs[0]["recipient"] == "bob"

    async def test_counter_offer_updates_amount_and_status(self, api):
        neg = await api.negotiate_price("alice", "bob", 200.0)
        neg_id = neg["id"]

        updated = await api.counter_offer(neg_id, "bob", 150.0)
        assert updated["current_amount"] == 150.0
        assert updated["status"] == NegotiationState.COUNTERED.value

    async def test_accept_sets_accepted_status(self, api):
        neg = await api.negotiate_price("alice", "bob", 300.0)
        neg_id = neg["id"]

        result = await api.accept_negotiation(neg_id, "bob")
        assert result["status"] == NegotiationState.ACCEPTED.value

    async def test_reject_sets_rejected_status(self, api):
        neg = await api.negotiate_price("alice", "bob", 400.0)
        neg_id = neg["id"]

        result = await api.reject_negotiation(neg_id, "bob")
        assert result["status"] == NegotiationState.REJECTED.value

    async def test_full_counter_then_accept_lifecycle(self, api, storage):
        """Propose → counter → counter → accept produces 4 thread messages."""
        neg = await api.negotiate_price("alice", "bob", 500.0, service_id="svc-deploy")
        neg_id = neg["id"]
        thread_id = neg["thread_id"]

        await api.counter_offer(neg_id, "bob", 400.0)
        await api.counter_offer(neg_id, "alice", 450.0)
        result = await api.accept_negotiation(neg_id, "bob")

        assert result["status"] == NegotiationState.ACCEPTED.value
        assert result["current_amount"] == 450.0

        msgs = await storage.get_thread(thread_id)
        assert len(msgs) == 4
        types = [m["message_type"] for m in msgs]
        assert types == [
            MessageType.PRICE_NEGOTIATION.value,
            MessageType.COUNTER_OFFER.value,
            MessageType.COUNTER_OFFER.value,
            MessageType.ACCEPT.value,
        ]


# ---------------------------------------------------------------------------
# Negative / edge cases
# ---------------------------------------------------------------------------


class TestNegotiationErrors:
    async def test_counter_offer_nonexistent_negotiation(self, api):
        with pytest.raises(ValueError, match="not found"):
            await api.counter_offer("nonexistent", "alice", 100.0)

    async def test_counter_by_non_party_raises(self, api):
        neg = await api.negotiate_price("alice", "bob", 100.0)
        with pytest.raises(ValueError, match="not a party"):
            await api.counter_offer(neg["id"], "charlie", 90.0)

    async def test_accept_already_rejected_raises(self, api):
        neg = await api.negotiate_price("alice", "bob", 100.0)
        await api.reject_negotiation(neg["id"], "bob")
        with pytest.raises(ValueError, match="not open"):
            await api.accept_negotiation(neg["id"], "alice")

    async def test_counter_after_accept_raises(self, api):
        neg = await api.negotiate_price("alice", "bob", 100.0)
        await api.accept_negotiation(neg["id"], "bob")
        with pytest.raises(ValueError, match="not open"):
            await api.counter_offer(neg["id"], "alice", 80.0)

    async def test_column_whitelist_rejects_invalid_field(self, storage):
        """H-11: update_negotiation rejects columns not in the whitelist."""
        neg_id = await storage.store_negotiation({
            "thread_id": "t1",
            "initiator": "a",
            "responder": "b",
            "proposed_amount": 100.0,
            "current_amount": 100.0,
            "status": NegotiationState.PROPOSED.value,
        })
        with pytest.raises(ValueError, match="Invalid negotiation columns"):
            await storage.update_negotiation(neg_id, {"initiator": "evil"})
