"""Pydantic models for the payment system.

All domain objects: PaymentIntent, Escrow, Subscription, Settlement.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums for status lifecycles
# ---------------------------------------------------------------------------

class IntentStatus(str, Enum):
    PENDING = "pending"
    CAPTURED = "captured"
    SETTLED = "settled"
    VOIDED = "voided"


class EscrowStatus(str, Enum):
    HELD = "held"
    RELEASED = "released"
    SETTLED = "settled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class SubscriptionInterval(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class PaymentIntent(BaseModel):
    """A payment intent from one agent to another."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: float
    description: str = ""
    idempotency_key: str | None = None
    status: IntentStatus = IntentStatus.PENDING
    settlement_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Escrow(BaseModel):
    """Funds held in escrow between two agents."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: float
    description: str = ""
    status: EscrowStatus = EscrowStatus.HELD
    settlement_id: str | None = None
    timeout_at: float | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Settlement(BaseModel):
    """A completed fund transfer record."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: float
    source_type: str  # "intent" or "escrow" or "subscription"
    source_id: str
    description: str = ""
    created_at: float = Field(default_factory=time.time)


class Subscription(BaseModel):
    """A recurring payment contract between two agents."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: float
    interval: SubscriptionInterval
    description: str = ""
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    cancelled_by: str | None = None
    next_charge_at: float = Field(default_factory=time.time)
    last_charged_at: float | None = None
    charge_count: int = 0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def compute_next_charge(self) -> float:
        """Compute the next charge timestamp based on interval."""
        now = time.time()
        intervals = {
            SubscriptionInterval.HOURLY: 3600,
            SubscriptionInterval.DAILY: 86400,
            SubscriptionInterval.WEEKLY: 604800,
            SubscriptionInterval.MONTHLY: 2592000,  # 30 days
        }
        return now + intervals[self.interval]
