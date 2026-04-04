"""Payments REST endpoints — /v1/payments/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.payments import (
    _cancel_escrow,
    _cancel_subscription,
    _capture_intent,
    _check_performance_escrow,
    _create_escrow,
    _create_intent,
    _create_performance_escrow,
    _create_split_intent,
    _create_subscription,
    _get_escrow,
    _get_intent,
    _get_payment_history,
    _get_subscription,
    _list_escrows,
    _list_intents,
    _list_subscriptions,
    _partial_capture,
    _process_due_subscriptions,
    _reactivate_subscription,
    _refund_intent,
    _refund_settlement,
    _release_escrow,
)

router = APIRouter(prefix="/v1/payments", tags=["payments"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class CreateIntentRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "payer": "agent-alice",
                "payee": "agent-bob",
                "amount": "10.00",
                "description": "Data analysis service",
                "currency": "CREDITS",
            }
        },
    )
    payer: str
    payee: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    description: str = ""
    currency: str = "CREDITS"
    metadata: dict[str, Any] | None = None


class CreateEscrowRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "payer": "agent-alice",
                "payee": "agent-bob",
                "amount": "50.00",
                "description": "Milestone delivery",
                "timeout_hours": 72,
            }
        },
    )
    payer: str
    payee: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    description: str = ""
    currency: str = "CREDITS"
    timeout_hours: int | None = None
    metadata: dict[str, Any] | None = None


class CreatePerformanceEscrowRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "payer": "agent-alice",
                "payee": "agent-bob",
                "amount": "25.00",
                "metric_name": "accuracy",
                "threshold": ">=0.95",
                "description": "ML model delivery",
            }
        },
    )
    payer: str
    payee: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    metric_name: str
    threshold: str
    description: str = ""


class PartialCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"amount": "15.00"}})
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)


class SplitEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payee: str
    percentage: float


class CreateSplitIntentRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "payer": "agent-alice",
                "amount": "100.00",
                "splits": [{"payee": "agent-bob", "percentage": 60}, {"payee": "agent-carol", "percentage": 40}],
                "description": "Revenue split",
            }
        },
    )
    payer: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    splits: list[SplitEntry]
    description: str = ""
    currency: str = "CREDITS"


class RefundSettlementRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"amount": "10.00", "reason": "Service not delivered"}}
    )
    amount: Decimal | None = Field(default=None, gt=0, le=1_000_000_000, decimal_places=2)
    reason: str = ""


class CreateSubscriptionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "payer": "agent-alice",
                "payee": "agent-bob",
                "amount": "9.99",
                "interval": "monthly",
                "description": "Premium data feed",
            }
        },
    )
    payer: str
    payee: str
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    interval: str
    description: str = ""
    currency: str = "CREDITS"
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    idem = tc.request.headers.get("idempotency-key")
    if idem and "idempotency_key" not in params:
        params["idempotency_key"] = idem
    return params


# ---------------------------------------------------------------------------
# Payment Intents
# ---------------------------------------------------------------------------


@router.post("/intents/split")
async def create_split_intent(
    body: CreateSplitIntentRequest,
    tc: ToolContext = Depends(require_tool("create_split_intent")),
):
    params = _inject_caller(
        tc,
        {
            "payer": body.payer,
            "amount": float(body.amount),
            "splits": [{"payee": s.payee, "percentage": s.percentage} for s in body.splits],
            "description": body.description,
            "currency": body.currency,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _create_split_intent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result, status_code=201)


@router.post("/intents")
async def create_intent(
    body: CreateIntentRequest,
    tc: ToolContext = Depends(require_tool("create_intent")),
):
    params = _inject_caller(
        tc,
        {
            "payer": body.payer,
            "payee": body.payee,
            "amount": float(body.amount),
            "description": body.description,
            "currency": body.currency,
            "metadata": body.metadata,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _create_intent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/payments/intents/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/intents")
async def list_intents(
    agent_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("list_intents")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        },
    )
    await check_ownership(tc, params)
    result = await _list_intents(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/intents/{intent_id}")
async def get_intent(
    intent_id: str,
    tc: ToolContext = Depends(require_tool("get_intent")),
):
    params = _inject_caller(tc, {"intent_id": intent_id})
    await check_ownership(tc, params)
    try:
        result = await _get_intent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/intents/{intent_id}/capture")
async def capture_intent(
    intent_id: str,
    tc: ToolContext = Depends(require_tool("capture_intent")),
):
    params = _inject_caller(tc, {"intent_id": intent_id})
    await check_ownership(tc, params)
    try:
        result = await _capture_intent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/intents/{intent_id}/partial-capture")
async def partial_capture(
    intent_id: str,
    body: PartialCaptureRequest,
    tc: ToolContext = Depends(require_tool("partial_capture")),
):
    params = _inject_caller(tc, {"intent_id": intent_id, "amount": float(body.amount)})
    await check_ownership(tc, params)
    try:
        result = await _partial_capture(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/intents/{intent_id}/refund")
async def refund_intent(
    intent_id: str,
    tc: ToolContext = Depends(require_tool("refund_intent")),
):
    params = _inject_caller(tc, {"intent_id": intent_id})
    await check_ownership(tc, params)
    try:
        result = await _refund_intent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Escrows
# ---------------------------------------------------------------------------


@router.post("/escrows/performance")
async def create_performance_escrow(
    body: CreatePerformanceEscrowRequest,
    tc: ToolContext = Depends(require_tool("create_performance_escrow")),
):
    params = _inject_caller(
        tc,
        {
            "payer": body.payer,
            "payee": body.payee,
            "amount": float(body.amount),
            "metric_name": body.metric_name,
            "threshold": body.threshold,
            "description": body.description,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _create_performance_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/payments/escrows/{result.get('escrow_id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.post("/escrows")
async def create_escrow(
    body: CreateEscrowRequest,
    tc: ToolContext = Depends(require_tool("create_escrow")),
):
    params = _inject_caller(
        tc,
        {
            "payer": body.payer,
            "payee": body.payee,
            "amount": float(body.amount),
            "description": body.description,
            "currency": body.currency,
            "timeout_hours": body.timeout_hours,
            "metadata": body.metadata,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _create_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/payments/escrows/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/escrows")
async def list_escrows(
    agent_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("list_escrows")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        },
    )
    await check_ownership(tc, params)
    result = await _list_escrows(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/escrows/{escrow_id}")
async def get_escrow(
    escrow_id: str,
    tc: ToolContext = Depends(require_tool("get_escrow")),
):
    params = _inject_caller(tc, {"escrow_id": escrow_id})
    await check_ownership(tc, params)
    try:
        result = await _get_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/escrows/{escrow_id}/release")
async def release_escrow(
    escrow_id: str,
    tc: ToolContext = Depends(require_tool("release_escrow")),
):
    params = _inject_caller(tc, {"escrow_id": escrow_id})
    await check_ownership(tc, params)
    try:
        result = await _release_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/escrows/{escrow_id}/cancel")
async def cancel_escrow(
    escrow_id: str,
    tc: ToolContext = Depends(require_tool("cancel_escrow")),
):
    params = _inject_caller(tc, {"escrow_id": escrow_id})
    await check_ownership(tc, params)
    try:
        result = await _cancel_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/escrows/{escrow_id}/check-performance")
async def check_performance_escrow(
    escrow_id: str,
    tc: ToolContext = Depends(require_tool("check_performance_escrow")),
):
    params = _inject_caller(tc, {"escrow_id": escrow_id})
    await check_ownership(tc, params)
    try:
        result = await _check_performance_escrow(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------


@router.post("/settlements/{settlement_id}/refund")
async def refund_settlement(
    settlement_id: str,
    body: RefundSettlementRequest | None = None,
    tc: ToolContext = Depends(require_tool("refund_settlement")),
):
    params: dict[str, Any] = {"settlement_id": settlement_id}
    if body:
        if body.amount is not None:
            params["amount"] = float(body.amount)
        params["reason"] = body.reason
    params = _inject_caller(tc, params)
    await check_ownership(tc, params)
    try:
        result = await _refund_settlement(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Payment History
# ---------------------------------------------------------------------------


@router.get("/history")
async def get_payment_history(
    agent_id: str,
    limit: int = 100,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("get_payment_history")),
):
    params = _inject_caller(tc, {"agent_id": agent_id, "limit": limit, "offset": offset})
    await check_ownership(tc, params)
    result = await _get_payment_history(tc.ctx, params)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@router.post("/subscriptions/process-due")
async def process_due_subscriptions(
    tc: ToolContext = Depends(require_tool("process_due_subscriptions")),
):
    params = _inject_caller(tc, {})
    await check_ownership(tc, params)
    try:
        result = await _process_due_subscriptions(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/subscriptions")
async def create_subscription(
    body: CreateSubscriptionRequest,
    tc: ToolContext = Depends(require_tool("create_subscription")),
):
    params = _inject_caller(
        tc,
        {
            "payer": body.payer,
            "payee": body.payee,
            "amount": float(body.amount),
            "interval": body.interval,
            "description": body.description,
            "currency": body.currency,
            "metadata": body.metadata,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _create_subscription(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/payments/subscriptions/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/subscriptions")
async def list_subscriptions(
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("list_subscriptions")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "status": status,
            "limit": limit,
            "offset": offset,
        },
    )
    await check_ownership(tc, params)
    result = await _list_subscriptions(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/subscriptions/{subscription_id}")
async def get_subscription(
    subscription_id: str,
    tc: ToolContext = Depends(require_tool("get_subscription")),
):
    params = _inject_caller(tc, {"subscription_id": subscription_id})
    await check_ownership(tc, params)
    try:
        result = await _get_subscription(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel_subscription(
    subscription_id: str,
    tc: ToolContext = Depends(require_tool("cancel_subscription")),
):
    params = _inject_caller(tc, {"subscription_id": subscription_id})
    await check_ownership(tc, params)
    try:
        result = await _cancel_subscription(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/subscriptions/{subscription_id}/reactivate")
async def reactivate_subscription(
    subscription_id: str,
    tc: ToolContext = Depends(require_tool("reactivate_subscription")),
):
    params = _inject_caller(tc, {"subscription_id": subscription_id})
    await check_ownership(tc, params)
    try:
        result = await _reactivate_subscription(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
