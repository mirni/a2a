"""Pydantic input/output models for Stripe MCP tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

class CreateCustomerInput(BaseModel):
    """Input for create_customer tool."""

    email: str = Field(..., description="Customer email address")
    name: str | None = Field(None, description="Customer full name")
    description: str | None = Field(None, description="Internal description")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(
        ..., description="Unique key to prevent duplicate customer creation"
    )


class CreatePaymentIntentInput(BaseModel):
    """Input for create_payment_intent tool."""

    amount: int = Field(..., gt=0, description="Amount in smallest currency unit (e.g. cents)")
    currency: str = Field(..., min_length=3, max_length=3, description="Three-letter ISO currency")
    customer_id: str | None = Field(None, description="Stripe customer ID")
    description: str | None = Field(None, description="Payment description")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(
        ..., description="Unique key to prevent duplicate payment creation"
    )


class ListChargesInput(BaseModel):
    """Input for list_charges tool."""

    limit: int = Field(10, ge=1, le=100, description="Number of charges to return (1-100)")
    starting_after: str | None = Field(None, description="Cursor for pagination (charge ID)")
    customer: str | None = Field(None, description="Filter by customer ID")
    created_gte: int | None = Field(None, description="Filter: created at or after (unix ts)")
    created_lte: int | None = Field(None, description="Filter: created at or before (unix ts)")


class CreateSubscriptionInput(BaseModel):
    """Input for create_subscription tool."""

    customer_id: str = Field(..., description="Stripe customer ID")
    price_id: str = Field(..., description="Stripe price ID for the subscription")
    quantity: int = Field(1, ge=1, description="Number of units")
    trial_period_days: int | None = Field(None, ge=0, description="Trial period in days")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(
        ..., description="Unique key to prevent duplicate subscription creation"
    )


class CreateRefundInput(BaseModel):
    """Input for create_refund tool."""

    payment_intent_id: str | None = Field(None, description="Payment intent to refund")
    charge_id: str | None = Field(None, description="Charge ID to refund (alt to payment_intent)")
    amount: int | None = Field(None, gt=0, description="Partial refund amount (omit for full)")
    reason: str | None = Field(
        None,
        description="Refund reason: duplicate, fraudulent, or requested_by_customer",
    )
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(
        ..., description="Unique key to prevent duplicate refund"
    )


class ListInvoicesInput(BaseModel):
    """Input for list_invoices tool."""

    limit: int = Field(10, ge=1, le=100, description="Number of invoices to return (1-100)")
    starting_after: str | None = Field(None, description="Cursor for pagination (invoice ID)")
    customer: str | None = Field(None, description="Filter by customer ID")
    status: str | None = Field(
        None, description="Filter by status: draft, open, paid, uncollectible, void"
    )
    created_gte: int | None = Field(None, description="Filter: created at or after (unix ts)")
    created_lte: int | None = Field(None, description="Filter: created at or before (unix ts)")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

class ToolResult(BaseModel):
    """Standard wrapper for tool results."""

    success: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None
