"""Identity REST endpoints — /v1/identity/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.identity import (
    _add_agent_to_org,
    _build_claim_chain,
    _create_org,
    _get_agent_identity,
    _get_agent_reputation,
    _get_claim_chains,
    _get_metric_averages,
    _get_metric_deltas,
    _get_org,
    _get_verified_claims,
    _ingest_metrics,
    _query_metrics,
    _register_agent,
    _remove_agent_from_org,
    _search_agents_by_metrics,
    _submit_metrics,
    _verify_agent,
)

router = APIRouter(prefix="/v1/identity", tags=["identity"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class RegisterAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    public_key: str | None = None


class VerifyAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str
    signature: str


class SubmitMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: dict[str, Any]
    data_source: str = "self_reported"


class CreateOrgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_name: str
    agent_id: str = ""


class AddMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    role: str = "member"


class IngestMetricsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    metrics: dict[str, Any]
    data_source: str = "self_reported"
    signature: str | None = None
    nonce: str | None = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    return params


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@router.post("/agents")
async def register_agent(
    body: RegisterAgentRequest,
    tc: ToolContext = Depends(require_tool("register_agent")),
):
    params = _inject_caller(tc, {"agent_id": body.agent_id, "public_key": body.public_key})
    await check_ownership(tc, params)
    try:
        result = await _register_agent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/identity/agents/{result.get('agent_id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/agents")
async def search_agents_by_metrics(
    metric_name: str,
    min_value: float | None = None,
    max_value: float | None = None,
    limit: int = 50,
    tc: ToolContext = Depends(require_tool("search_agents_by_metrics")),
):
    params = _inject_caller(
        tc,
        {
            "metric_name": metric_name,
            "min_value": min_value,
            "max_value": max_value,
            "limit": limit,
        },
    )
    await check_ownership(tc, params)
    result = await _search_agents_by_metrics(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/agents/{agent_id}")
async def get_agent_identity(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("get_agent_identity")),
):
    params = _inject_caller(tc, {"agent_id": agent_id})
    await check_ownership(tc, params)
    try:
        result = await _get_agent_identity(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/agents/{agent_id}/verify")
async def verify_agent(
    agent_id: str,
    body: VerifyAgentRequest,
    tc: ToolContext = Depends(require_tool("verify_agent")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "message": body.message,
            "signature": body.signature,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _verify_agent(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/agents/{agent_id}/reputation")
async def get_agent_reputation(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("get_agent_reputation")),
):
    params = _inject_caller(tc, {"agent_id": agent_id})
    await check_ownership(tc, params)
    try:
        result = await _get_agent_reputation(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/agents/{agent_id}/claims")
async def get_verified_claims(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("get_verified_claims")),
):
    params = _inject_caller(tc, {"agent_id": agent_id})
    await check_ownership(tc, params)
    try:
        result = await _get_verified_claims(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/agents/{agent_id}/metrics")
async def submit_metrics(
    agent_id: str,
    body: SubmitMetricsRequest,
    tc: ToolContext = Depends(require_tool("submit_metrics")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "metrics": body.metrics,
            "data_source": body.data_source,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _submit_metrics(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/agents/{agent_id}/claim-chains")
async def build_claim_chain(
    agent_id: str,
    tc: ToolContext = Depends(require_tool("build_claim_chain")),
):
    params = _inject_caller(tc, {"agent_id": agent_id})
    await check_ownership(tc, params)
    try:
        result = await _build_claim_chain(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/agents/{agent_id}/claim-chains")
async def get_claim_chains(
    agent_id: str,
    limit: int = 10,
    tc: ToolContext = Depends(require_tool("get_claim_chains")),
):
    params = _inject_caller(tc, {"agent_id": agent_id, "limit": limit})
    await check_ownership(tc, params)
    result = await _get_claim_chains(tc.ctx, params)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Orgs
# ---------------------------------------------------------------------------


@router.post("/orgs")
async def create_org(
    body: CreateOrgRequest,
    tc: ToolContext = Depends(require_tool("create_org")),
):
    params = _inject_caller(tc, {"org_name": body.org_name, "agent_id": body.agent_id})
    await check_ownership(tc, params)
    try:
        result = await _create_org(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/identity/orgs/{result.get('org_id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/orgs/{org_id}")
async def get_org(
    org_id: str,
    tc: ToolContext = Depends(require_tool("get_org")),
):
    params = _inject_caller(tc, {"org_id": org_id})
    await check_ownership(tc, params)
    result = await _get_org(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/orgs/{org_id}/members")
async def add_agent_to_org(
    org_id: str,
    body: AddMemberRequest,
    tc: ToolContext = Depends(require_tool("add_agent_to_org")),
):
    params = _inject_caller(tc, {"org_id": org_id, "agent_id": body.agent_id, "role": body.role})
    await check_ownership(tc, params)
    try:
        result = await _add_agent_to_org(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.delete("/orgs/{org_id}/members/{agent_id}")
async def remove_agent_from_org(
    org_id: str,
    agent_id: str,
    tc: ToolContext = Depends(require_tool("remove_agent_from_org")),
):
    params = _inject_caller(tc, {"org_id": org_id, "agent_id": agent_id})
    await check_ownership(tc, params)
    try:
        result = await _remove_agent_from_org(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Time-series metrics
# ---------------------------------------------------------------------------


@router.post("/metrics/ingest")
async def ingest_metrics(
    body: IngestMetricsRequest,
    tc: ToolContext = Depends(require_tool("ingest_metrics")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": body.agent_id,
            "metrics": body.metrics,
            "data_source": body.data_source,
            "signature": body.signature,
            "nonce": body.nonce,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _ingest_metrics(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/metrics")
async def query_metrics(
    agent_id: str,
    metric_name: str,
    since: float | None = None,
    limit: int = 100,
    tc: ToolContext = Depends(require_tool("query_metrics")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "metric_name": metric_name,
            "since": since,
            "limit": limit,
        },
    )
    await check_ownership(tc, params)
    result = await _query_metrics(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/metrics/deltas")
async def get_metric_deltas(
    agent_id: str,
    metric_name: str | None = None,
    tc: ToolContext = Depends(require_tool("get_metric_deltas")),
):
    params = _inject_caller(tc, {"agent_id": agent_id, "metric_name": metric_name})
    await check_ownership(tc, params)
    result = await _get_metric_deltas(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/metrics/averages")
async def get_metric_averages(
    agent_id: str,
    period: str = "30d",
    tc: ToolContext = Depends(require_tool("get_metric_averages")),
):
    params = _inject_caller(tc, {"agent_id": agent_id, "period": period})
    await check_ownership(tc, params)
    result = await _get_metric_averages(tc.ctx, params)
    return await finalize_response(tc, result)
