"""MCP server setup and tool registration for Stripe connector."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError as PydanticValidationError

from src.client import StripeClient
from src.errors import ValidationError
from src.models import (
    CreateCustomerInput,
    CreatePaymentIntentInput,
    CreateRefundInput,
    CreateSubscriptionInput,
    ListChargesInput,
    ListInvoicesInput,
    ToolResult,
)
from src.tools import (
    create_customer as _create_customer,
)
from src.tools import (
    create_payment_intent as _create_payment_intent,
)
from src.tools import (
    create_refund as _create_refund,
)
from src.tools import (
    create_subscription as _create_subscription,
)
from src.tools import (
    get_balance as _get_balance,
)
from src.tools import (
    list_charges as _list_charges,
)
from src.tools import (
    list_invoices as _list_invoices,
)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Manage StripeClient lifecycle."""
    client = StripeClient()
    try:
        yield {"stripe_client": client}
    finally:
        await client.close()


mcp = FastMCP(
    name="stripe-connector",
    instructions=(
        "Production-grade Stripe connector. Exposes tools for customer management, "
        "payments, subscriptions, refunds, invoices, and balance retrieval. "
        "All write operations require an idempotency_key for safety."
    ),
    lifespan=lifespan,
)


def _validation_error_result(exc: PydanticValidationError) -> str:
    """Format Pydantic validation errors into a ToolResult JSON string."""
    details = {"validation_errors": exc.errors(include_url=False, include_input=False)}
    result = ToolResult(
        success=False,
        error=ValidationError("Input validation failed", details=details).to_dict(),
    )
    return result.model_dump_json()


def _result_to_json(result: ToolResult) -> str:
    """Serialize a ToolResult to JSON for MCP response."""
    return result.model_dump_json()


# --------------------------------------------------------------------------
# Tool registrations
# --------------------------------------------------------------------------


@mcp.tool(
    name="create_customer",
    description=(
        "Create a Stripe customer. Requires email and idempotency_key. Optional: name, description, metadata."
    ),
)
async def create_customer_tool(
    email: str,
    idempotency_key: str,
    name: str | None = None,
    description: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    try:
        input_model = CreateCustomerInput(
            email=email,
            name=name,
            description=description,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _create_customer(client, input_model)
    return _result_to_json(result)


@mcp.tool(
    name="create_payment_intent",
    description=(
        "Create a Stripe PaymentIntent. Requires amount (in cents), currency, "
        "and idempotency_key. Optional: customer_id, description, metadata."
    ),
)
async def create_payment_intent_tool(
    amount: int,
    currency: str,
    idempotency_key: str,
    customer_id: str | None = None,
    description: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    try:
        input_model = CreatePaymentIntentInput(
            amount=amount,
            currency=currency,
            customer_id=customer_id,
            description=description,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _create_payment_intent(client, input_model)
    return _result_to_json(result)


@mcp.tool(
    name="list_charges",
    description=(
        "List Stripe charges with optional filters. "
        "Supports pagination via starting_after, filtering by customer and creation date."
    ),
)
async def list_charges_tool(
    limit: int = 10,
    starting_after: str | None = None,
    customer: str | None = None,
    created_gte: int | None = None,
    created_lte: int | None = None,
) -> str:
    try:
        input_model = ListChargesInput(
            limit=limit,
            starting_after=starting_after,
            customer=customer,
            created_gte=created_gte,
            created_lte=created_lte,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _list_charges(client, input_model)
    return _result_to_json(result)


@mcp.tool(
    name="create_subscription",
    description=(
        "Create a Stripe subscription. Requires customer_id, price_id, and idempotency_key. "
        "Optional: quantity, trial_period_days, metadata."
    ),
)
async def create_subscription_tool(
    customer_id: str,
    price_id: str,
    idempotency_key: str,
    quantity: int = 1,
    trial_period_days: int | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    try:
        input_model = CreateSubscriptionInput(
            customer_id=customer_id,
            price_id=price_id,
            quantity=quantity,
            trial_period_days=trial_period_days,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _create_subscription(client, input_model)
    return _result_to_json(result)


@mcp.tool(
    name="get_balance",
    description="Retrieve the current Stripe account balance.",
)
async def get_balance_tool() -> str:
    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _get_balance(client)
    return _result_to_json(result)


@mcp.tool(
    name="create_refund",
    description=(
        "Create a Stripe refund. Requires idempotency_key and either payment_intent_id or "
        "charge_id. Optional: amount (for partial refund), reason, metadata."
    ),
)
async def create_refund_tool(
    idempotency_key: str,
    payment_intent_id: str | None = None,
    charge_id: str | None = None,
    amount: int | None = None,
    reason: str | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    try:
        input_model = CreateRefundInput(
            payment_intent_id=payment_intent_id,
            charge_id=charge_id,
            amount=amount,
            reason=reason,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    try:
        result = await _create_refund(client, input_model)
    except ValidationError as exc:
        result = ToolResult(success=False, error=exc.to_dict())
    return _result_to_json(result)


@mcp.tool(
    name="list_invoices",
    description=(
        "List Stripe invoices with optional filters. "
        "Supports pagination, filtering by customer, status, and creation date."
    ),
)
async def list_invoices_tool(
    limit: int = 10,
    starting_after: str | None = None,
    customer: str | None = None,
    status: str | None = None,
    created_gte: int | None = None,
    created_lte: int | None = None,
) -> str:
    try:
        input_model = ListInvoicesInput(
            limit=limit,
            starting_after=starting_after,
            customer=customer,
            status=status,
            created_gte=created_gte,
            created_lte=created_lte,
        )
    except PydanticValidationError as exc:
        return _validation_error_result(exc)

    ctx = mcp.get_context()
    client: StripeClient = ctx.request_context.lifespan_context["stripe_client"]
    result = await _list_invoices(client, input_model)
    return _result_to_json(result)


def main() -> None:
    """Run the MCP server via stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
