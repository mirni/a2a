"""Trust REST endpoints — /v1/trust/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from gateway.src.deps.tool_context import ToolContext, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.trust import (
    _check_sla_compliance,
    _delete_server,
    _get_trust_score,
    _register_server,
    _search_servers,
    _update_server,
)

router = APIRouter(prefix="/v1/trust", tags=["trust"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class RegisterServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    transport_type: str = "http"
    server_id: str | None = None


class UpdateServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    url: str | None = None


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


@router.post("/servers")
async def register_server(
    body: RegisterServerRequest,
    tc: ToolContext = Depends(require_tool("register_server")),
):
    params = _inject_caller(
        tc,
        {
            "name": body.name,
            "url": body.url,
            "transport_type": body.transport_type,
            "server_id": body.server_id,
        },
    )
    try:
        result = await _register_server(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/trust/servers/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/servers")
async def search_servers(
    name_contains: str | None = None,
    min_score: float | None = None,
    limit: int = 100,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("search_servers")),
):
    params = _inject_caller(
        tc,
        {
            "name_contains": name_contains,
            "min_score": min_score,
            "limit": limit,
            "offset": offset,
        },
    )
    result = await _search_servers(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/servers/{server_id}/score")
async def get_trust_score(
    server_id: str,
    window: str = "24h",
    recompute: bool = False,
    tc: ToolContext = Depends(require_tool("get_trust_score")),
):
    params = _inject_caller(
        tc,
        {"server_id": server_id, "window": window, "recompute": recompute},
    )
    try:
        result = await _get_trust_score(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.put("/servers/{server_id}")
async def update_server(
    server_id: str,
    body: UpdateServerRequest,
    tc: ToolContext = Depends(require_tool("update_server")),
):
    params = _inject_caller(
        tc,
        {"server_id": server_id, "name": body.name, "url": body.url},
    )
    try:
        result = await _update_server(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.delete("/servers/{server_id}")
async def delete_server(
    server_id: str,
    tc: ToolContext = Depends(require_tool("delete_server")),
):
    params = _inject_caller(tc, {"server_id": server_id})
    try:
        result = await _delete_server(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/servers/{server_id}/sla")
async def check_sla_compliance(
    server_id: str,
    claimed_uptime: float = 99.0,
    tc: ToolContext = Depends(require_tool("check_sla_compliance")),
):
    params = _inject_caller(
        tc,
        {"server_id": server_id, "claimed_uptime": claimed_uptime},
    )
    try:
        result = await _check_sla_compliance(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
