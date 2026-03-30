"""High-level messaging API for agent-to-agent communication and price negotiation."""

from __future__ import annotations

import json
import time
import uuid

from .crypto import MessageCrypto
from .models import EncryptionMetadata, Message, MessageType, NegotiationState
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
        encrypt: bool = False,
        sender_private_key_hex: str | None = None,
        recipient_public_key_hex: str | None = None,
    ) -> Message:
        """Create and store a message. Returns the Message object.

        Args:
            sender: Sender agent ID.
            recipient: Recipient agent ID.
            message_type: Type of message.
            subject: Message subject line.
            body: Message body (plaintext). If encrypt=True, this will be
                encrypted before storage.
            metadata: Optional metadata dict.
            thread_id: Optional thread ID for conversation threading.
            encrypt: If True, encrypt the body using X25519 + AES-256-GCM.
            sender_private_key_hex: Sender's Ed25519 private key hex.
                Required when encrypt=True.
            recipient_public_key_hex: Recipient's X25519 public key hex
                (derived from their Ed25519 private key seed). Required
                when encrypt=True.

        Returns:
            The stored Message object. If encrypted, body contains base64
            ciphertext and encryption_metadata is populated.

        Raises:
            ValueError: If encrypt=True but keys are not provided.
        """
        encrypted = False
        encryption_metadata = None

        if encrypt:
            if not sender_private_key_hex or not recipient_public_key_hex:
                raise ValueError("sender_private_key_hex and recipient_public_key_hex are required when encrypt=True")

            # Derive the recipient's X25519 public key from their Ed25519 private seed.
            # The caller passes recipient_public_key_hex which may be either:
            # - An Ed25519 public key (in which case we can't derive X25519 from it)
            # - An X25519 public key already derived
            # Our convention: pass the X25519 public key derived from the recipient's
            # Ed25519 seed. The API layer or caller handles the derivation.
            ciphertext_b64, nonce_b64, ephemeral_pub_hex = MessageCrypto.encrypt_message(
                sender_private_key_hex=sender_private_key_hex,
                recipient_public_key_hex=recipient_public_key_hex,
                plaintext=body,
            )
            body = ciphertext_b64
            encrypted = True
            encryption_metadata = EncryptionMetadata(
                nonce=nonce_b64,
                algorithm="x25519-aes256gcm",
                ephemeral_public_key=ephemeral_pub_hex,
            )

        msg = Message(
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            subject=subject,
            body=body,
            metadata=metadata or {},
            thread_id=thread_id,
            encrypted=encrypted,
            encryption_metadata=encryption_metadata,
        )
        await self._storage.store_message(msg)
        return msg

    async def get_messages(
        self,
        agent_id: str,
        thread_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        decrypt_key: str | None = None,
        sender_public_key_hex: str | None = None,
    ) -> list[dict]:
        """Get messages for an agent, optionally filtered by thread.

        Args:
            agent_id: The agent whose messages to retrieve.
            thread_id: Optional thread filter.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip for pagination.
            decrypt_key: Recipient's Ed25519 private key hex. If provided,
                encrypted messages will be decrypted in-place before return.
            sender_public_key_hex: Sender's Ed25519 public key hex, used to
                derive their X25519 public key for decryption context. Not
                needed when ephemeral key is stored in encryption_metadata.

        Returns:
            List of message dicts. Encrypted messages are decrypted if
            decrypt_key is provided.
        """
        messages = await self._storage.get_messages(agent_id, thread_id=thread_id, limit=limit, offset=offset)

        if decrypt_key:
            for msg in messages:
                if msg.get("encrypted") and msg.get("encryption_metadata"):
                    enc_meta = msg["encryption_metadata"]
                    if isinstance(enc_meta, str):
                        enc_meta = json.loads(enc_meta)
                    try:
                        plaintext = MessageCrypto.decrypt_message(
                            recipient_private_key_hex=decrypt_key,
                            sender_public_key_hex=enc_meta["ephemeral_public_key"],
                            ciphertext=msg["body"],
                            nonce=enc_meta["nonce"],
                        )
                        msg["body"] = plaintext
                    except Exception:
                        # Decryption failed — leave ciphertext in place
                        pass

        return messages

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

        neg_id = await self._storage.store_negotiation(
            {
                "thread_id": thread_id,
                "initiator": initiator,
                "responder": responder,
                "proposed_amount": amount,
                "current_amount": amount,
                "status": NegotiationState.PROPOSED.value,
                "service_id": service_id,
                "expires_at": expires_at,
            }
        )

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
        assert neg is not None
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

        await self._storage.update_negotiation(
            negotiation_id,
            {
                "current_amount": new_amount,
                "status": NegotiationState.COUNTERED.value,
            },
        )

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.COUNTER_OFFER,
            subject=f"Counter offer: {new_amount}",
            body=f"Counter-proposing {new_amount}",
            metadata={"negotiation_id": negotiation_id, "amount": new_amount},
            thread_id=neg["thread_id"],
        )

        result = await self._storage.get_negotiation(negotiation_id)
        assert result is not None
        return result

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

        await self._storage.update_negotiation(
            negotiation_id,
            {
                "status": NegotiationState.ACCEPTED.value,
            },
        )

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.ACCEPT,
            subject="Negotiation accepted",
            body=f"Accepted at {neg['current_amount']}",
            metadata={"negotiation_id": negotiation_id, "amount": neg["current_amount"]},
            thread_id=neg["thread_id"],
        )

        result = await self._storage.get_negotiation(negotiation_id)
        assert result is not None
        return result

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

        await self._storage.update_negotiation(
            negotiation_id,
            {
                "status": NegotiationState.REJECTED.value,
            },
        )

        await self.send_message(
            sender=agent_id,
            recipient=other,
            message_type=MessageType.REJECT,
            subject="Negotiation rejected",
            body="Rejected",
            metadata={"negotiation_id": negotiation_id},
            thread_id=neg["thread_id"],
        )

        result = await self._storage.get_negotiation(negotiation_id)
        assert result is not None
        return result

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
