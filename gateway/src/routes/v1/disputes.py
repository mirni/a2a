"""Disputes REST endpoints — /v1/disputes/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from gateway.src.deps.tool_context import ToolContext, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.payments import (
    _get_dispute,
    _list_disputes,
    _open_dispute,
    _resolve_dispute,
    _respond_to_dispute,
)

router = APIRouter(prefix="/v1/disputes", tags=["disputes"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class OpenDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    escrow_id: str
    opener: str
    reason: str = ""


class RespondToDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respondent: str
    response: str


class ResolveDisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str
    resolved_by: str
    notes: str = ""


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


@router.post("")
async def open_dispute(
    body: OpenDisputeRequest,
    tc: ToolContext = Depends(require_tool("open_dispute")),
):
    params = _inject_caller(
        tc,
        {
            "escrow_id": body.escrow_id,
            "opener": body.opener,
            "reason": body.reason,
        },
    )
    try:
        result = await _open_dispute(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/disputes/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("")
async def list_disputes(
    agent_id: str,
    limit: int = 50,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("list_disputes")),
):
    params = _inject_caller(
        tc,
        {"agent_id": agent_id, "limit": limit, "offset": offset},
    )
    result = await _list_disputes(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/{dispute_id}")
async def get_dispute(
    dispute_id: str,
    tc: ToolContext = Depends(require_tool("get_dispute")),
):
    params = _inject_caller(tc, {"dispute_id": dispute_id})
    try:
        result = await _get_dispute(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/{dispute_id}/respond")
async def respond_to_dispute(
    dispute_id: str,
    body: RespondToDisputeRequest,
    tc: ToolContext = Depends(require_tool("respond_to_dispute")),
):
    params = _inject_caller(
        tc,
        {
            "dispute_id": dispute_id,
            "respondent": body.respondent,
            "response": body.response,
        },
    )
    try:
        result = await _respond_to_dispute(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/{dispute_id}/resolve")
async def resolve_dispute(
    dispute_id: str,
    body: ResolveDisputeRequest,
    tc: ToolContext = Depends(require_tool("resolve_dispute")),
):
    params = _inject_caller(
        tc,
        {
            "dispute_id": dispute_id,
            "resolution": body.resolution,
            "resolved_by": body.resolved_by,
            "notes": body.notes,
        },
    )
    try:
        result = await _resolve_dispute(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
