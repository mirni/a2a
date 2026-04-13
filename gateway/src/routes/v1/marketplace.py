"""Marketplace REST endpoints — /v1/marketplace/."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.marketplace import (
    _atlas_broker,
    _atlas_discover,
    _atlas_preflight,
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
from gateway.src.validators import AGENT_ID_PATTERN, sanitize_text

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

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, v: str) -> str:
        return sanitize_text(v) if isinstance(v, str) else v


class UpdateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    endpoint: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("description", mode="before")
    @classmethod
    def _sanitize_description(cls, v: str) -> str:
        return sanitize_text(v) if isinstance(v, str) else v


class RateServiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int
    review: str = ""

    @field_validator("review", mode="before")
    @classmethod
    def _sanitize_review(cls, v: str) -> str:
        return sanitize_text(v) if isinstance(v, str) else v


class AtlasDiscoverRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "query": "analytics",
                "budget": 10.0,
                "min_trust_score": 50.0,
                "prefer": "trust",
                "capabilities": ["predict"],
                "limit": 5,
            }
        },
    )
    query: str = Field(max_length=500)
    budget: Decimal | None = Field(default=None, ge=0, le=1_000_000_000)
    min_trust_score: float | None = Field(default=None, ge=0, le=100)
    prefer: str = "trust"
    capabilities: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=50)

    @field_validator("query", mode="before")
    @classmethod
    def _sanitize_query(cls, v: str) -> str:
        return sanitize_text(v) if isinstance(v, str) else v


class AtlasPreflightRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "service_id": "svc-abc123",
                "min_trust_score": 60.0,
                "expected_cost": 1.0,
            }
        },
    )
    service_id: str = Field(max_length=256)
    min_trust_score: float | None = Field(default=None, ge=0, le=100)
    expected_cost: Decimal | None = Field(default=None, ge=0, le=1_000_000_000)


class AtlasBrokerRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "query": "data analysis",
                "payer": "agent-alice",
                "budget": 50.0,
                "description": "Brokered analytics job",
            }
        },
    )
    query: str = Field(max_length=500)
    payer: str = Field(max_length=128, pattern=AGENT_ID_PATTERN)
    budget: Decimal | None = Field(default=None, ge=0, le=1_000_000_000)
    min_trust_score: float | None = Field(default=None, ge=0, le=100)
    prefer: str = "trust"
    description: str = Field(default="", max_length=2000)

    @field_validator("query", "description", mode="before")
    @classmethod
    def _sanitize_text_fields(cls, v: str) -> str:
        return sanitize_text(v) if isinstance(v, str) else v


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


# ---------------------------------------------------------------------------
# Atlas Discovery & Brokering
# ---------------------------------------------------------------------------


@router.post("/atlas/discover")
async def atlas_discover(
    body: AtlasDiscoverRequest,
    tc: ToolContext = Depends(require_tool("atlas_discover")),  # noqa: B008
):
    params = _inject_caller(
        tc,
        {
            "query": body.query,
            "budget": float(body.budget) if body.budget is not None else None,
            "min_trust_score": body.min_trust_score,
            "prefer": body.prefer,
            "capabilities": body.capabilities,
            "limit": body.limit,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _atlas_discover(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/atlas/preflight")
async def atlas_preflight(
    body: AtlasPreflightRequest,
    tc: ToolContext = Depends(require_tool("atlas_preflight")),  # noqa: B008
):
    params = _inject_caller(
        tc,
        {
            "service_id": body.service_id,
            "min_trust_score": body.min_trust_score,
            "expected_cost": float(body.expected_cost) if body.expected_cost is not None else None,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _atlas_preflight(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/atlas/broker")
async def atlas_broker(
    body: AtlasBrokerRequest,
    tc: ToolContext = Depends(require_tool("atlas_broker")),  # noqa: B008
):
    params = _inject_caller(
        tc,
        {
            "query": body.query,
            "payer": body.payer,
            "budget": float(body.budget) if body.budget is not None else None,
            "min_trust_score": body.min_trust_score,
            "prefer": body.prefer,
            "description": body.description,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _atlas_broker(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
