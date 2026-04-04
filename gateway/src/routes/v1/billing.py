"""Billing REST endpoints — /v1/billing/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.config import GatewayConfig
from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import error_response
from gateway.src.tools.billing import (
    _convert_currency,
    _create_wallet,
    _deposit,
    _estimate_cost,
    _freeze_wallet,
    _get_agent_leaderboard,
    _get_balance,
    _get_budget_status,
    _get_exchange_rate,
    _get_metrics_timeseries,
    _get_revenue_report,
    _get_service_analytics,
    _get_transactions,
    _get_usage_summary,
    _get_volume_discount,
    _set_budget_cap,
    _unfreeze_wallet,
    _withdraw,
)

router = APIRouter(prefix="/v1/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid" per CLAUDE.md)
# ---------------------------------------------------------------------------


class CreateWalletRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"agent_id": "agent-alice", "initial_balance": "100.00", "signup_bonus": True}},
    )
    agent_id: str
    initial_balance: Decimal = Decimal("0")
    signup_bonus: bool = True


class DepositRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"amount": "50.00", "currency": "CREDITS", "description": "Top-up via Stripe"}},
    )
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    currency: str = "CREDITS"
    description: str = ""


class WithdrawRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"amount": "25.00", "currency": "CREDITS", "description": "Payout to external wallet"}
        },
    )
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    currency: str = "CREDITS"
    description: str = ""


class BudgetCapRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"daily_cap": "100.00", "monthly_cap": "2000.00", "alert_threshold": 0.8}},
    )
    daily_cap: Decimal | None = None
    monthly_cap: Decimal | None = None
    alert_threshold: float = 0.8


class ConvertCurrencyRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"amount": "100.00", "from_currency": "CREDITS", "to_currency": "USD"}},
    )
    amount: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)
    from_currency: str
    to_currency: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/wallets/{agent_id}/balance")
async def get_balance(
    agent_id: str,
    currency: str = "CREDITS",
    tc: ToolContext = Depends(require_tool("get_balance")),
):
    params = {
        "agent_id": agent_id,
        "currency": currency,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _get_balance(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/wallets")
async def create_wallet(
    body: CreateWalletRequest,
    tc: ToolContext = Depends(require_tool("create_wallet")),
):
    params = {
        "agent_id": body.agent_id,
        "initial_balance": float(body.initial_balance),
        "signup_bonus": body.signup_bonus,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _create_wallet(tc.ctx, params)
    return await finalize_response(tc, result, status_code=201)


@router.post("/wallets/{agent_id}/deposit")
async def deposit(
    agent_id: str,
    body: DepositRequest,
    tc: ToolContext = Depends(require_tool("deposit")),
):
    params: dict[str, Any] = {
        "agent_id": agent_id,
        "amount": float(body.amount),
        "currency": body.currency,
        "description": body.description,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)

    # P0 #1: Enforce per-tier deposit limits
    config = GatewayConfig.from_env()
    tier_limit = config.deposit_limits.get(tc.agent_tier)
    if tier_limit is not None and float(body.amount) > tier_limit:
        from gateway.src.deps.tool_context import _ResponseError

        resp = await error_response(
            403,
            f"Deposit amount exceeds {tc.agent_tier}-tier limit of {tier_limit:,} credits",
            "deposit_limit_exceeded",
            request=tc.request,
        )
        raise _ResponseError(resp)

    idem = tc.request.headers.get("idempotency-key")
    if idem:
        params["idempotency_key"] = idem
    result = await _deposit(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/wallets/{agent_id}/withdraw")
async def withdraw(
    agent_id: str,
    body: WithdrawRequest,
    tc: ToolContext = Depends(require_tool("withdraw")),
):
    params: dict[str, Any] = {
        "agent_id": agent_id,
        "amount": float(body.amount),
        "currency": body.currency,
        "description": body.description,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    idem = tc.request.headers.get("idempotency-key")
    if idem:
        params["idempotency_key"] = idem
    result = await _withdraw(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/wallets/{agent_id}/freeze")
async def freeze_wallet(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("freeze_wallet")),
):
    params = {"agent_id": agent_id, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _freeze_wallet(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/wallets/{agent_id}/unfreeze")
async def unfreeze_wallet(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("unfreeze_wallet")),
):
    params = {"agent_id": agent_id, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _unfreeze_wallet(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/transactions")
async def get_transactions(
    agent_id: str,
    limit: int = 100,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("get_transactions")),
):
    params = {
        "agent_id": agent_id,
        "limit": limit,
        "offset": offset,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _get_transactions(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/usage")
async def get_usage_summary(
    agent_id: str,
    since: float | None = None,
    tc: ToolContext = Depends(require_tool("get_usage_summary")),
):
    params = {"agent_id": agent_id, "since": since, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _get_usage_summary(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/analytics")
async def get_service_analytics(
    agent_id: str,
    since: float | None = None,
    tc: ToolContext = Depends(require_tool("get_service_analytics")),
):
    params = {"agent_id": agent_id, "since": since, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _get_service_analytics(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/revenue")
async def get_revenue_report(
    agent_id: str,
    limit: int = 50,
    tc: ToolContext = Depends(require_tool("get_revenue_report")),
):
    params = {"agent_id": agent_id, "limit": limit, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _get_revenue_report(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/timeseries")
async def get_metrics_timeseries(
    agent_id: str,
    interval: str = "hour",
    since: float | None = None,
    limit: int = 24,
    tc: ToolContext = Depends(require_tool("get_metrics_timeseries")),
):
    params = {
        "agent_id": agent_id,
        "interval": interval,
        "since": since,
        "limit": limit,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _get_metrics_timeseries(tc.ctx, params)
    return await finalize_response(tc, result)


@router.put("/wallets/{agent_id}/budget")
async def set_budget_cap(
    agent_id: str,
    body: BudgetCapRequest,
    tc: ToolContext = Depends(require_tool("set_budget_cap")),
):
    params = {
        "agent_id": agent_id,
        "daily_cap": float(body.daily_cap) if body.daily_cap is not None else None,
        "monthly_cap": float(body.monthly_cap) if body.monthly_cap is not None else None,
        "alert_threshold": body.alert_threshold,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _set_budget_cap(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/wallets/{agent_id}/budget")
async def get_budget_status(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("get_budget_status")),
):
    params = {"agent_id": agent_id, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier}
    await check_ownership(tc, params)
    result = await _get_budget_status(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/leaderboard")
async def get_agent_leaderboard(
    metric: str = "spend",
    limit: int = 10,
    tc: ToolContext = Depends(require_tool("get_agent_leaderboard")),
):
    result = await _get_agent_leaderboard(
        tc.ctx,
        {"metric": metric, "limit": limit, "_caller_agent_id": tc.agent_id, "_caller_tier": tc.agent_tier},
    )
    return await finalize_response(tc, result)


@router.get("/discounts")
async def get_volume_discount(
    agent_id: str,
    tool_name: str,
    quantity: int = 1,
    tc: ToolContext = Depends(require_tool("get_volume_discount")),
):
    params = {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "quantity": quantity,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _get_volume_discount(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/estimate")
async def estimate_cost(
    tool_name: str,
    quantity: int = 1,
    agent_id: str | None = None,
    tc: ToolContext = Depends(require_tool("estimate_cost")),
):
    params = {
        "tool_name": tool_name,
        "quantity": quantity,
        "agent_id": agent_id,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    if agent_id:
        await check_ownership(tc, params)
    result = await _estimate_cost(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/exchange-rates")
async def get_exchange_rate(
    from_currency: str,
    to_currency: str,
    tc: ToolContext = Depends(require_tool("get_exchange_rate")),
):
    result = await _get_exchange_rate(
        tc.ctx,
        {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "_caller_agent_id": tc.agent_id,
            "_caller_tier": tc.agent_tier,
        },
    )
    return await finalize_response(tc, result)


@router.post("/wallets/{agent_id}/convert")
async def convert_currency(
    agent_id: str,
    body: ConvertCurrencyRequest,
    tc: ToolContext = Depends(require_tool("convert_currency")),
):
    params = {
        "agent_id": agent_id,
        "amount": float(body.amount),
        "from_currency": body.from_currency,
        "to_currency": body.to_currency,
        "_caller_agent_id": tc.agent_id,
        "_caller_tier": tc.agent_tier,
    }
    await check_ownership(tc, params)
    result = await _convert_currency(tc.ctx, params)
    return await finalize_response(tc, result)
