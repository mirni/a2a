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


class NegotiationState(StrEnum):
    PROPOSED = "proposed"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
