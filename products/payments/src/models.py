"""Pydantic models for the payment system.

All domain objects: PaymentIntent, Escrow, Subscription, Settlement.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ---------------------------------------------------------------------------
# Enums for status lifecycles
# ---------------------------------------------------------------------------


class IntentStatus(StrEnum):
    PENDING = "pending"
    CAPTURED = "captured"
    SETTLED = "settled"
    VOIDED = "voided"


class EscrowStatus(StrEnum):
    HELD = "held"
    RELEASED = "released"
    SETTLED = "settled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class SettlementStatus(StrEnum):
    SETTLED = "settled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class RefundStatus(StrEnum):
    COMPLETED = "completed"


class SubscriptionInterval(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class PaymentIntent(BaseModel):
    """A payment intent from one agent to another."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "payer": "agent-alice-001",
                    "payee": "agent-bob-002",
                    "amount": "49.99",
                    "description": "Code review service",
                    "idempotency_key": "idem-20260328-001",
                    "status": "pending",
                    "metadata": {"project": "a2a-platform"},
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: Decimal
    description: str = ""
    idempotency_key: str | None = None
    status: IntentStatus = IntentStatus.PENDING
    settlement_id: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> float:
        return float(v)


class Escrow(BaseModel):
    """Funds held in escrow between two agents."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "payer": "agent-alice-001",
                    "payee": "agent-charlie-003",
                    "amount": "250.00",
                    "description": "Data pipeline delivery escrow",
                    "status": "held",
                    "timeout_at": 1711699200.0,
                    "metadata": {"contract_id": "ct-9182"},
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: Decimal
    description: str = ""
    status: EscrowStatus = EscrowStatus.HELD
    settlement_id: str | None = None
    timeout_at: float | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> float:
        return float(v)


class Settlement(BaseModel):
    """A completed fund transfer record."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "payer": "agent-alice-001",
                    "payee": "agent-bob-002",
                    "amount": "49.99",
                    "source_type": "intent",
                    "source_id": "abc123def456",
                    "description": "Code review service settlement",
                    "status": "settled",
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: Decimal
    source_type: str  # "intent" or "escrow" or "subscription"
    source_id: str
    description: str = ""
    status: SettlementStatus = SettlementStatus.SETTLED
    created_at: float = Field(default_factory=time.time)

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> float:
        return float(v)


class Subscription(BaseModel):
    """A recurring payment contract between two agents."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "payer": "agent-dave-004",
                    "payee": "agent-eve-005",
                    "amount": "9.99",
                    "interval": "monthly",
                    "description": "Premium monitoring subscription",
                    "status": "active",
                    "charge_count": 0,
                    "metadata": {"plan": "premium"},
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    payer: str
    payee: str
    amount: Decimal
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

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> float:
        return float(v)

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


class Refund(BaseModel):
    """A refund against a settlement (full or partial)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "settlement_id": "settle-abc123",
                    "amount": "25.00",
                    "reason": "Service not delivered",
                    "status": "completed",
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    settlement_id: str
    amount: Decimal
    reason: str = ""
    status: RefundStatus = RefundStatus.COMPLETED
    created_at: float = Field(default_factory=time.time)

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> float:
        return float(v)
