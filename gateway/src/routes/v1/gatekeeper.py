"""Gatekeeper REST endpoints — /v1/gatekeeper/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

import time

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.gatekeeper_metrics import GatekeeperMetrics
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
    name: str = Field(max_length=128)
    scope: str = "economic"
    # ``z3_smt2`` → raw SMT-LIB2 text; ``json_policy`` → JSON-encoded
    # :class:`products.gatekeeper.src.policy.JsonPolicy` (compiled to
    # SMT-LIB2 on the server).
    language: str = Field(default="z3_smt2", pattern=r"^(z3_smt2|json_policy)$")
    expression: str = Field(max_length=1_000_000)
    description: str = Field(default="", max_length=1000)


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
    agent_id: str = Field(max_length=128)
    properties: list[PropertySpecRequest] = Field(min_length=1, max_length=100)
    scope: str = "economic"
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    webhook_url: str | None = None
    idempotency_key: str | None = None
    metadata: dict[str, Any] | None = None


class VerifyProofRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"proof_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2"}
        },
    )
    proof_hash: str = Field(max_length=128)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    # v1.2.4: accept Idempotency-Key HTTP header on POST /v1/gatekeeper/jobs
    # for consistency with /v1/payments/*. Body field still works; header
    # is only consulted when the body did not provide one so explicit body
    # values win (deterministic contract).
    idem = tc.request.headers.get("idempotency-key")
    if idem and not params.get("idempotency_key"):
        params["idempotency_key"] = idem
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
    t0 = time.perf_counter()
    try:
        result = await _submit_verification(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    # CRIT-2 (audit v1.2.1 + v1.2.2): failed verification jobs must not
    # charge the caller. When the verifier backend raises (or the job
    # otherwise ends in a terminal FAILED/TIMEOUT/ERROR state before the
    # response is returned) we waive the per-call cost and zero out the
    # cost fields in the response so the integrator can see they were
    # not billed. ``billed_cost`` is a new explicit alias introduced in
    # v1.2.3 so the distinction between "catalog price" and "amount
    # debited" is always visible.
    if result.get("status") in {"failed", "timeout"} or result.get("result") == "error":
        tc.cost = 0.0
        result["cost"] = "0"
        result["billed_cost"] = "0"
    else:
        # On success, surface the same number under ``billed_cost`` so
        # the contract is consistent across success/failure responses.
        result["billed_cost"] = result.get("cost", "0")

    # v1.2.4: emit per-tier/per-result telemetry (histogram of wall-clock
    # duration, histogram of solver time, counter of jobs, summed cost).
    # We only have the end-to-end route latency here because the
    # verifier's own solver_ms is not plumbed through the tool layer; the
    # histogram still differentiates tiers and outcomes, which is the
    # primary SRE and CMO dashboard ask.
    try:
        cost_float = float(result.get("cost") or 0)
    except (TypeError, ValueError):
        cost_float = 0.0
    await GatekeeperMetrics.observe_job(
        tier=tc.agent_tier,
        result=result.get("result") or result.get("status") or "unknown",
        cost_credits=cost_float,
        duration_ms=duration_ms,
        solver_ms=duration_ms,
    )

    location = f"/v1/gatekeeper/jobs/{result.get('job_id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/jobs")
async def list_verification_jobs(
    agent_id: str,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
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
    try:
        result = await _list_verification_jobs(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
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
    try:
        result = await _verify_proof(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
