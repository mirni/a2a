"""Pydantic input/output models for Stripe MCP tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class CreateCustomerInput(BaseModel):
    """Input for create_customer tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "email": "jane.doe@example.com",
                    "name": "Jane Doe",
                    "description": "Enterprise plan  customer",
                    "metadata": {"tier": "enterprise"},
                    "idempotency_key": "cust_create_abc123",
                }
            ]
        },
    )

    email: str = Field(..., description="Customer email address")
    name: str | None = Field(None, description="Customer full name")
    description: str | None = Field(None, description="Internal description")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(..., description="Unique key to prevent duplicate customer creation")


class CreatePaymentIntentInput(BaseModel):
    """Input for create_payment_intent tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "amount": 5000,
                    "currency": "usd",
                    "customer_id": "cus_Nq1cOk3bT3lXWz",
                    "description": "Order #1042 — 2 widgets",
                    "metadata": {"order_id": "1042"},
                    "idempotency_key": "pi_create_order1042",
                }
            ]
        },
    )

    amount: int = Field(..., gt=0, description="Amount in smallest currency unit (e.g. cents)")
    currency: str = Field(..., min_length=3, max_length=3, description="Three-letter ISO currency")
    customer_id: str | None = Field(None, description="Stripe customer ID")
    description: str | None = Field(None, description="Payment description")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(..., description="Unique key to prevent duplicate payment creation")


class ListChargesInput(BaseModel):
    """Input for list_charges tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "limit": 25,
                    "customer": "cus_Nq1cOk3bT3lXWz",
                    "created_gte": 1700000000,
                    "created_lte": 1710000000,
                }
            ]
        },
    )

    limit: int = Field(10, ge=1, le=100, description="Number of charges to return (1-100)")
    starting_after: str | None = Field(None, description="Cursor for pagination (charge ID)")
    customer: str | None = Field(None, description="Filter by customer ID")
    created_gte: int | None = Field(None, description="Filter: created at or after (unix ts)")
    created_lte: int | None = Field(None, description="Filter: created at or before (unix ts)")


class CreateSubscriptionInput(BaseModel):
    """Input for create_subscription tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "customer_id": "cus_Nq1cOk3bT3lXWz",
                    "price_id": "price_1NzRfV2eZvKYlo2C6f3pgZ1A",
                    "quantity": 1,
                    "trial_period_days": 14,
                    "metadata": {"plan": "pro"},
                    "idempotency_key": "sub_create_cust_Nq1c_pro",
                }
            ]
        },
    )

    customer_id: str = Field(..., description="Stripe customer ID")
    price_id: str = Field(..., description="Stripe price ID for the subscription")
    quantity: int = Field(1, ge=1, description="Number of units")
    trial_period_days: int | None = Field(None, ge=0, description="Trial period in days")
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(..., description="Unique key to prevent duplicate subscription creation")


class CreateRefundInput(BaseModel):
    """Input for create_refund tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "payment_intent_id": "pi_3NzRfV2eZvKYlo2C0wH5bH1a",
                    "amount": 2500,
                    "reason": "requested_by_customer",
                    "metadata": {"support_ticket": "TICK-887"},
                    "idempotency_key": "refund_pi3Nz_partial",
                }
            ]
        },
    )

    payment_intent_id: str | None = Field(None, description="Payment intent to refund")
    charge_id: str | None = Field(None, description="Charge ID to refund (alt to payment_intent)")
    amount: int | None = Field(None, gt=0, description="Partial refund amount (omit for full)")
    reason: str | None = Field(
        None,
        description="Refund reason: duplicate, fraudulent, or requested_by_customer",
    )
    metadata: dict[str, str] | None = Field(None, description="Arbitrary key-value metadata")
    idempotency_key: str = Field(..., description="Unique key to prevent duplicate refund")


class ListInvoicesInput(BaseModel):
    """Input for list_invoices tool."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "limit": 20,
                    "customer": "cus_Nq1cOk3bT3lXWz",
                    "status": "paid",
                    "created_gte": 1700000000,
                }
            ]
        },
    )

    limit: int = Field(10, ge=1, le=100, description="Number of invoices to return (1-100)")
    starting_after: str | None = Field(None, description="Cursor for pagination (invoice ID)")
    customer: str | None = Field(None, description="Filter by customer ID")
    status: str | None = Field(None, description="Filter by status: draft, open, paid, uncollectible, void")
    created_gte: int | None = Field(None, description="Filter: created at or after (unix ts)")
    created_lte: int | None = Field(None, description="Filter: created at or before (unix ts)")


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """Standard wrapper for tool results."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "data": {"id": "cus_Nq1cOk3bT3lXWz", "object": "customer"},
                    "error": None,
                }
            ]
        },
    )

    success: bool
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None
