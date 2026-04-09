"""Gatekeeper REST endpoints — /v1/gatekeeper/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.gatekeeper import (
    _cancel_verification,
    _get_proof,
    _get_verification_status,
    _list_verification_jobs,
    _submit_verification,
    _verify_proof,
)

router = APIRouter(prefix="/v1/gatekeeper", tags=["gatekeeper"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class PropertySpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    scope: str = "economic"
    language: str = "z3_smt2"
    expression: str
    description: str = ""


class SubmitVerificationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "agent_id": "agent-alice",
                "properties": [
                    {
                        "name": "balance_conservation",
                        "scope": "economic",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (> x 0))",
                        "description": "Check positive balance",
                    }
                ],
                "scope": "economic",
                "timeout_seconds": 300,
            }
        },
    )
    agent_id: str
    properties: list[PropertySpecRequest]
    scope: str = "economic"
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    webhook_url: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None


class VerifyProofRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "proof_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"
            }
        },
    )
    proof_hash: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    return params


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@router.post("/jobs")
async def submit_verification(
    body: SubmitVerificationRequest,
    tc: ToolContext = Depends(require_tool("submit_verification")),  # noqa: B008
):
    params = _inject_caller(
        tc,
        {
            "agent_id": body.agent_id,
            "properties": [p.model_dump() for p in body.properties],
            "scope": body.scope,
            "timeout_seconds": body.timeout_seconds,
            "webhook_url": body.webhook_url,
            "idempotency_key": body.idempotency_key,
            "metadata": body.metadata,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _submit_verification(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/gatekeeper/jobs/{result.get('job_id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/jobs")
async def list_verification_jobs(
    agent_id: str,
    status: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    tc: ToolContext = Depends(require_tool("list_verification_jobs")),  # noqa: B008
):
    params = _inject_caller(
        tc,
        {
            "agent_id": agent_id,
            "status": status,
            "limit": limit,
            "cursor": cursor,
        },
    )
    await check_ownership(tc, params)
    result = await _list_verification_jobs(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/jobs/{job_id}")
async def get_verification_status(
    job_id: str,
    tc: ToolContext = Depends(require_tool("get_verification_status")),  # noqa: B008
):
    params = _inject_caller(tc, {"job_id": job_id})
    try:
        result = await _get_verification_status(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/jobs/{job_id}/cancel")
async def cancel_verification(
    job_id: str,
    tc: ToolContext = Depends(require_tool("cancel_verification")),  # noqa: B008
):
    params = _inject_caller(tc, {"job_id": job_id})
    try:
        result = await _cancel_verification(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Proofs
# ---------------------------------------------------------------------------


@router.get("/proofs/{proof_id}")
async def get_proof(
    proof_id: str,
    tc: ToolContext = Depends(require_tool("get_proof")),  # noqa: B008
):
    params = _inject_caller(tc, {"proof_id": proof_id})
    try:
        result = await _get_proof(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/proofs/verify")
async def verify_proof(
    body: VerifyProofRequest,
    tc: ToolContext = Depends(require_tool("verify_proof")),  # noqa: B008
):
    params = {"proof_hash": body.proof_hash}
    result = await _verify_proof(tc.ctx, params)
    return await finalize_response(tc, result)
