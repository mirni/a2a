"""Messaging REST endpoints — /v1/messaging/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.messaging import (
    _get_messages,
    _negotiate_price,
    _send_message,
)

router = APIRouter(prefix="/v1/messaging", tags=["messaging"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str
    recipient: str
    message_type: str
    subject: str = ""
    body: str = ""
    metadata: dict[str, Any] | None = None
    thread_id: str | None = None


class NegotiatePriceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initiator: str
    responder: str
    amount: Decimal
    service_id: str = ""
    expires_hours: int = 24


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    return params


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/messages")
async def send_message(
    body: SendMessageRequest,
    tc: ToolContext = Depends(require_tool("send_message")),
):
    params = _inject_caller(
        tc,
        {
            "sender": body.sender,
            "recipient": body.recipient,
            "message_type": body.message_type,
            "subject": body.subject,
            "body": body.body,
            "metadata": body.metadata,
            "thread_id": body.thread_id,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _send_message(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result, status_code=201)


@router.get("/messages")
async def get_messages(
    agent_id: str,
    thread_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("get_messages")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "thread_id": thread_id,
            "limit": limit,
            "offset": offset,
        },
    )
    await check_ownership(tc, params)
    result = await _get_messages(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/negotiations")
async def negotiate_price(
    body: NegotiatePriceRequest,
    tc: ToolContext = Depends(require_tool("negotiate_price")),
):
    params = _inject_caller(
        tc,
        {
            "initiator": body.initiator,
            "responder": body.responder,
            "amount": float(body.amount),
            "service_id": body.service_id,
            "expires_hours": body.expires_hours,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _negotiate_price(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
