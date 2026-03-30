"""Data models for the agent-to-agent messaging system."""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MessageType(StrEnum):
    TEXT = "text"
    PRICE_NEGOTIATION = "price_negotiation"
    TASK_SPECIFICATION = "task_specification"
    COUNTER_OFFER = "counter_offer"
    ACCEPT = "accept"
    REJECT = "reject"


class EncryptionMetadata(BaseModel):
    """Metadata required to decrypt an encrypted message body.

    Stored alongside the ciphertext so the recipient can reconstruct
    the shared secret and decrypt.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "nonce": "dGVzdG5vbmNlMTIz",
                    "algorithm": "x25519-aes256gcm",
                    "ephemeral_public_key": "ab" * 32,
                }
            ]
        },
    )

    nonce: str = Field(description="Base64-encoded AES-256-GCM nonce (12 bytes).")
    algorithm: str = Field(
        default="x25519-aes256gcm",
        description="Encryption algorithm identifier.",
    )
    ephemeral_public_key: str = Field(description="Hex-encoded ephemeral X25519 public key used for ECDH.")


class Message(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "sender": "agent-alice-001",
                    "recipient": "agent-bob-002",
                    "message_type": "price_negotiation",
                    "subject": "API integration quote",
                    "body": "Proposing $150 for the REST API integration task.",
                    "metadata": {"urgency": "high"},
                    "thread_id": "thread-7a3f",
                    "encrypted": False,
                    "encryption_metadata": None,
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    sender: str
    recipient: str
    message_type: MessageType
    subject: str = ""
    body: str = ""
    metadata: dict = Field(default_factory=dict)
    thread_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    read_at: float | None = None
    encrypted: bool = Field(default=False, description="Whether the body is encrypted.")
    encryption_metadata: EncryptionMetadata | None = Field(
        default=None,
        description="Encryption metadata (nonce, algorithm, ephemeral key). Present only when encrypted=True.",
    )


class NegotiationState(StrEnum):
    PROPOSED = "proposed"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
