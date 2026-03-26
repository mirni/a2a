"""Tool handlers for Stripe MCP connector.

Each function implements the business logic for one MCP tool.
All inputs are validated via Pydantic models before reaching these handlers.
"""

from __future__ import annotations

from typing import Any

from src.client import StripeClient
from errors import ConnectorError, ValidationError
from src.models import (
    CreateCustomerInput,
    CreatePaymentIntentInput,
    CreateRefundInput,
    CreateSubscriptionInput,
    ListChargesInput,
    ListInvoicesInput,
    ToolResult,
)


async def create_customer(client: StripeClient, input: CreateCustomerInput) -> ToolResult:
    """Create a Stripe customer with idempotency protection."""
    data: dict[str, Any] = {"email": input.email}
    if input.name:
        data["name"] = input.name
    if input.description:
        data["description"] = input.description
    if input.metadata:
        data["metadata"] = input.metadata

    try:
        result = await client.post(
            "customers", data, idempotency_key=input.idempotency_key
        )
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def create_payment_intent(
    client: StripeClient, input: CreatePaymentIntentInput
) -> ToolResult:
    """Create a Stripe PaymentIntent with idempotency protection."""
    data: dict[str, Any] = {
        "amount": input.amount,
        "currency": input.currency.lower(),
    }
    if input.customer_id:
        data["customer"] = input.customer_id
    if input.description:
        data["description"] = input.description
    if input.metadata:
        data["metadata"] = input.metadata

    try:
        result = await client.post(
            "payment_intents", data, idempotency_key=input.idempotency_key
        )
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def list_charges(client: StripeClient, input: ListChargesInput) -> ToolResult:
    """List charges with optional filters and pagination."""
    params: dict[str, Any] = {"limit": input.limit}
    if input.starting_after:
        params["starting_after"] = input.starting_after
    if input.customer:
        params["customer"] = input.customer
    if input.created_gte is not None:
        params["created[gte]"] = input.created_gte
    if input.created_lte is not None:
        params["created[lte]"] = input.created_lte

    try:
        result = await client.get("charges", params=params)
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def create_subscription(
    client: StripeClient, input: CreateSubscriptionInput
) -> ToolResult:
    """Create a Stripe subscription with idempotency protection."""
    data: dict[str, Any] = {
        "customer": input.customer_id,
        "items": {"0": {"price": input.price_id, "quantity": str(input.quantity)}},
    }
    if input.trial_period_days is not None:
        data["trial_period_days"] = input.trial_period_days
    if input.metadata:
        data["metadata"] = input.metadata

    try:
        result = await client.post(
            "subscriptions", data, idempotency_key=input.idempotency_key
        )
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def get_balance(client: StripeClient) -> ToolResult:
    """Retrieve the current Stripe account balance."""
    try:
        result = await client.get("balance")
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def create_refund(client: StripeClient, input: CreateRefundInput) -> ToolResult:
    """Create a refund with idempotency protection."""
    if not input.payment_intent_id and not input.charge_id:
        raise ValidationError(
            "Either payment_intent_id or charge_id must be provided",
            details={"fields": ["payment_intent_id", "charge_id"]},
        )

    data: dict[str, Any] = {}
    if input.payment_intent_id:
        data["payment_intent"] = input.payment_intent_id
    if input.charge_id:
        data["charge"] = input.charge_id
    if input.amount is not None:
        data["amount"] = input.amount
    if input.reason:
        data["reason"] = input.reason
    if input.metadata:
        data["metadata"] = input.metadata

    try:
        result = await client.post(
            "refunds", data, idempotency_key=input.idempotency_key
        )
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())


async def list_invoices(client: StripeClient, input: ListInvoicesInput) -> ToolResult:
    """List invoices with optional filters and pagination."""
    params: dict[str, Any] = {"limit": input.limit}
    if input.starting_after:
        params["starting_after"] = input.starting_after
    if input.customer:
        params["customer"] = input.customer
    if input.status:
        params["status"] = input.status
    if input.created_gte is not None:
        params["created[gte]"] = input.created_gte
    if input.created_lte is not None:
        params["created[lte]"] = input.created_lte

    try:
        result = await client.get("invoices", params=params)
        return ToolResult(success=True, data=result)
    except ConnectorError as exc:
        return ToolResult(success=False, error=exc.to_dict())
