"""Data models for the agent-to-agent messaging system."""

from __future__ import annotations

import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TEXT = "text"
    PRICE_NEGOTIATION = "price_negotiation"
    TASK_SPECIFICATION = "task_specification"
    COUNTER_OFFER = "counter_offer"
    ACCEPT = "accept"
    REJECT = "reject"


class Message(BaseModel):
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


class NegotiationState(str, Enum):
    PROPOSED = "proposed"
    COUNTERED = "countered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
