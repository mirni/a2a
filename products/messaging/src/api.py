"""High-level messaging API for agent-to-agent communication and price negotiation."""

from __future__ import annotations

import time
import uuid

from .models import Message, MessageType, NegotiationState
from .storage import MessageStorage


class MessagingAPI:
    """Public API for the messaging module."""

    def __init__(self, storage: MessageStorage) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self,
        sender: str,
        recipient: str,
        message_type: MessageType,
        subject: str = "",
        body: str = "",
        metadata: dict | None = None,
        thread_id: str | None = None,
    ) -> Message:
        """Create and store a message. Returns the Message object."""
        msg = Message(
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            subject=subject,
            body=body,
            metadata=metadata or {},
            thread_id=thread_id,
        )
        await self._storage.store_message(msg)
        return msg

    async def get_messages(
        self,
        agent_id: str,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get messages for an agent, optionally filtered by thread."""
        return await self._storage.get_messages(agent_id, thread_id=thread_id, limit=limit)

    async def get_thread(self, thread_id: str) -> list[dict]:
        """Get all messages in a thread, ordered oldest first."""
        return await self._storage.get_thread(thread_id)

    # ------------------------------------------------------------------
    # Negotiation
    # ------------------------------------------------------------------

    async def negotiate_price(
        self,
        initiator: str,
        responder: str,
        amount: float,
        service_id: str = "",
        expires_hours: float = 24,
    ) -> dict:
        """Start a price negotiation. Creates a thread, a negotiation record, and a proposal message."""
        thread_id = uuid.uuid4().hex
        expires_at = time.time() + expires_hours * 3600

        neg_id = await self._storage.store_negotiation({
            "thread_id": thread_id,
            "initiator": initiator,
            "responder": responder,
            "proposed_amount": amount,
            "current_amount": amount,
            "status": NegotiationState.PROPOSED.value,
            "service_id": service_id,
            "expires_at": expires_at,
        })

        # Send the proposal message
        await self.send_message(
            sender=initiator,
            recipient=responder,
            message_type=MessageType.PRICE_NEGOTIATION,
            subject=f"Price proposal: {amount}",
            body=f"Proposing {amount} for service {service_id}",
            metadata={"negotiation_id": neg_id, "amount": amount},
            thread_id=thread_id,
        )

        neg = await self._storage.get_negotiation(neg_id)
        return neg

    async def counter_offer(
        self,
        negotiation_id: str,
        agent_id: str,
        new_amount: float,
    ) -> dict:
        """Submit a counter-offer on an existing negotiation."""
        neg = await self._storage.get_negotiation(negotiation_id)
        if neg is None:
            raise ValueError(f"Negotiation {negotiation_id} not found")

        self._assert_party(neg, agent_id)
        self._assert_open(neg)

        other = neg["responder"] if agent_id == neg["initiator"] else neg["initiator"]

        await self._storage.update_negotiation(negotiation_id, {
            "current_amount": new_amount,
            "status": NegotiationState.COUNTERED.value,
        })

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.COUNTER_OFFER,
            subject=f"Counter offer: {new_amount}",
            body=f"Counter-proposing {new_amount}",
            metadata={"negotiation_id": negotiation_id, "amount": new_amount},
            thread_id=neg["thread_id"],
        )

        return await self._storage.get_negotiation(negotiation_id)

    async def accept_negotiation(
        self,
        negotiation_id: str,
        agent_id: str,
    ) -> dict:
        """Accept the current negotiation terms."""
        neg = await self._storage.get_negotiation(negotiation_id)
        if neg is None:
            raise ValueError(f"Negotiation {negotiation_id} not found")

        self._assert_party(neg, agent_id)
        self._assert_open(neg)

        other = neg["responder"] if agent_id == neg["initiator"] else neg["initiator"]

        await self._storage.update_negotiation(negotiation_id, {
            "status": NegotiationState.ACCEPTED.value,
        })

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.ACCEPT,
            subject="Negotiation accepted",
            body=f"Accepted at {neg['current_amount']}",
            metadata={"negotiation_id": negotiation_id, "amount": neg["current_amount"]},
            thread_id=neg["thread_id"],
        )

        return await self._storage.get_negotiation(negotiation_id)

    async def reject_negotiation(
        self,
        negotiation_id: str,
        agent_id: str,
    ) -> dict:
        """Reject the negotiation."""
        neg = await self._storage.get_negotiation(negotiation_id)
        if neg is None:
            raise ValueError(f"Negotiation {negotiation_id} not found")

        self._assert_party(neg, agent_id)
        self._assert_open(neg)

        other = neg["responder"] if agent_id == neg["initiator"] else neg["initiator"]

        await self._storage.update_negotiation(negotiation_id, {
            "status": NegotiationState.REJECTED.value,
        })

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.REJECT,
            subject="Negotiation rejected",
            body="Rejected",
            metadata={"negotiation_id": negotiation_id},
            thread_id=neg["thread_id"],
        )

        return await self._storage.get_negotiation(negotiation_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_party(neg: dict, agent_id: str) -> None:
        """Raise ValueError if agent_id is not a party to the negotiation."""
        if agent_id not in (neg["initiator"], neg["responder"]):
            raise ValueError(f"Agent {agent_id} is not a party to this negotiation")

    @staticmethod
    def _assert_open(neg: dict) -> None:
        """Raise ValueError if the negotiation is not in an open state."""
        open_states = {NegotiationState.PROPOSED.value, NegotiationState.COUNTERED.value}
        if neg["status"] not in open_states:
            raise ValueError(f"Negotiation is not open (status: {neg['status']})")
