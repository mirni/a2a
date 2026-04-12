"""Formal verification and proof tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tools._validators import (
    check_caller_owns_agent_id as _check_caller_owns_agent_id,
)
from gateway.src.tools._validators import (
    check_caller_owns_job as _check_caller_owns_job,
)


async def _submit_verification(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    _check_caller_owns_agent_id(params)
    job = await ctx.gatekeeper_api.submit_verification(
        agent_id=params["agent_id"],
        properties=params["properties"],
        scope=params.get("scope", "economic"),
        timeout_seconds=params.get("timeout_seconds", 300),
        webhook_url=params.get("webhook_url"),
        idempotency_key=params.get("idempotency_key"),
        metadata=params.get("metadata"),
    )
    # ``result`` is surfaced alongside the job metadata so observability
    # (per-tier histograms, dashboards) and SDK convenience wrappers
    # (``prove_policy``) do not need a second round trip when the mock
    # or synchronous verifier has already produced a terminal outcome.
    return {
        "job_id": job.id,
        "status": job.status.value,
        "result": job.result.value if job.result else None,
        "cost": str(job.cost),
        "created_at": job.created_at,
    }


async def _get_verification_status(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job = await ctx.gatekeeper_api.get_verification_status(params["job_id"])
    _check_caller_owns_job(job.agent_id, params)
    # v1.2.2 audit CRIT-2: failed jobs must show cost:"0" + billed_cost:"0"
    # so the caller can verify they were not billed without having to
    # cross-reference their wallet balance.
    status_value = job.status.value
    if status_value in {"failed", "timeout"} or (job.result and job.result.value == "error"):
        cost_str = "0"
        billed_cost_str = "0"
    else:
        cost_str = str(job.cost)
        billed_cost_str = cost_str
    return {
        "job_id": job.id,
        "agent_id": job.agent_id,
        "status": status_value,
        "result": job.result.value if job.result else None,
        "proof_artifact_id": job.proof_artifact_id,
        "cost": cost_str,
        "billed_cost": billed_cost_str,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


async def _list_verification_jobs(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    _check_caller_owns_agent_id(params)
    jobs = await ctx.gatekeeper_api.list_verification_jobs(
        agent_id=params["agent_id"],
        status=params.get("status"),
        limit=params.get("limit", 50),
        cursor=params.get("cursor"),
    )
    job_rows: list[dict[str, Any]] = []
    for j in jobs:
        job_status = j.status.value
        job_result = j.result.value if j.result else None
        # v1.2.2 audit CRIT-2: failed/timeout/error jobs report cost="0".
        if job_status in {"failed", "timeout"} or job_result == "error":
            cost_str = "0"
        else:
            cost_str = str(j.cost)
        job_rows.append(
            {
                "job_id": j.id,
                "status": job_status,
                "result": job_result,
                "cost": cost_str,
                "billed_cost": cost_str,
                "created_at": j.created_at,
            }
        )
    return {"jobs": job_rows, "count": len(job_rows)}


async def _cancel_verification(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    # Fetch job first to check ownership before mutating
    job = await ctx.gatekeeper_api.get_verification_status(params["job_id"])
    _check_caller_owns_job(job.agent_id, params)
    cancelled = await ctx.gatekeeper_api.cancel_verification(params["job_id"])
    return {
        "job_id": cancelled.id,
        "status": cancelled.status.value,
    }


async def _get_proof(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    proof = await ctx.gatekeeper_api.get_proof(params["proof_id"])
    _check_caller_owns_job(proof.agent_id, params)
    return {
        "proof_id": proof.id,
        "job_id": proof.job_id,
        "agent_id": proof.agent_id,
        "result": proof.result.value,
        "proof_hash": proof.proof_hash,
        "valid_until": proof.valid_until,
        "property_results": proof.property_results,
        "created_at": proof.created_at,
    }


async def _verify_proof(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.gatekeeper_api.verify_proof(params["proof_hash"])
