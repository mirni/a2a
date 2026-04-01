"""Marketplace REST endpoints — /v1/marketplace/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.marketplace import (
    _best_match,
    _deactivate_service,
    _get_service,
    _get_service_ratings_tool,
    _list_strategies,
    _rate_service_tool,
    _register_service,
    _search_agents,
    _search_services,
    _update_service,
)

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class RegisterServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str
    name: str
    description: str
    category: str
    tools: list[str] | None = None
    tags: list[str] | None = None
    endpoint: str = ""
    pricing: dict[str, Any] | None = None


class UpdateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    endpoint: str | None = None
    metadata: dict[str, Any] | None = None


class RateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int
    review: str = ""


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


@router.post("/services")
async def register_service(
    body: RegisterServiceRequest,
    tc: ToolContext = Depends(require_tool("register_service")),
):
    params = _inject_caller(
        tc,
        {
            "provider_id": body.provider_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "tools": body.tools or [],
            "tags": body.tags or [],
            "endpoint": body.endpoint,
            "pricing": body.pricing,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _register_service(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/marketplace/services/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/services")
async def search_services(
    query: str | None = None,
    category: str | None = None,
    tags: str | None = None,
    max_cost: float | None = None,
    limit: int = 20,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("search_services")),
):
    params = _inject_caller(
        tc,
        {
            "query": query,
            "category": category,
            "tags": tags.split(",") if tags else None,
            "max_cost": max_cost,
            "limit": limit,
            "offset": offset,
        },
    )
    await check_ownership(tc, params)
    result = await _search_services(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/services/{service_id}")
async def get_service(
    service_id: str,
    tc: ToolContext = Depends(require_tool("get_service")),
):
    params = _inject_caller(tc, {"service_id": service_id})
    await check_ownership(tc, params)
    try:
        result = await _get_service(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.put("/services/{service_id}")
async def update_service(
    service_id: str,
    body: UpdateServiceRequest,
    tc: ToolContext = Depends(require_tool("update_service")),
):
    params = _inject_caller(
        tc,
        {
            "service_id": service_id,
            "name": body.name,
            "description": body.description,
            "category": body.category,
            "tags": body.tags,
            "endpoint": body.endpoint,
            "metadata": body.metadata,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _update_service(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/services/{service_id}/deactivate")
async def deactivate_service(
    service_id: str,
    tc: ToolContext = Depends(require_tool("deactivate_service")),
):
    params = _inject_caller(tc, {"service_id": service_id})
    await check_ownership(tc, params)
    try:
        result = await _deactivate_service(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/services/{service_id}/ratings")
async def rate_service(
    service_id: str,
    body: RateServiceRequest,
    tc: ToolContext = Depends(require_tool("rate_service")),
):
    params = _inject_caller(
        tc,
        {
            "service_id": service_id,
            "agent_id": tc.agent_id,
            "rating": body.rating,
            "review": body.review,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _rate_service_tool(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/services/{service_id}/ratings")
async def get_service_ratings(
    service_id: str,
    limit: int = 20,
    tc: ToolContext = Depends(require_tool("get_service_ratings")),
):
    params = _inject_caller(tc, {"service_id": service_id, "limit": limit})
    await check_ownership(tc, params)
    result = await _get_service_ratings_tool(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/match")
async def best_match(
    query: str,
    budget: float | None = None,
    min_trust_score: float | None = None,
    prefer: str = "trust",
    limit: int = 5,
    tc: ToolContext = Depends(require_tool("best_match")),
):
    params = _inject_caller(
        tc,
        {
            "query": query,
            "budget": budget,
            "min_trust_score": min_trust_score,
            "prefer": prefer,
            "limit": limit,
        },
    )
    await check_ownership(tc, params)
    result = await _best_match(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/agents")
async def search_agents(
    query: str,
    limit: int = 20,
    tc: ToolContext = Depends(require_tool("search_agents")),
):
    params = _inject_caller(tc, {"query": query, "limit": limit})
    await check_ownership(tc, params)
    result = await _search_agents(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/strategies")
async def list_strategies(
    tags: str | None = None,
    max_cost: float | None = None,
    limit: int = 50,
    tc: ToolContext = Depends(require_tool("list_strategies")),
):
    params = _inject_caller(
        tc,
        {
            "tags": tags.split(",") if tags else None,
            "max_cost": max_cost,
            "limit": limit,
        },
    )
    await check_ownership(tc, params)
    result = await _list_strategies(tc.ctx, params)
    return await finalize_response(tc, result)
