"""Formal verification and proof tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tool_errors import ToolForbiddenError

ADMIN_TIER = "admin"


def _check_caller_owns_agent_id(params: dict[str, Any]) -> None:
    """Raise ToolForbiddenError if caller is not admin and agent_id != caller."""
    caller = params.get("_caller_agent_id")
    tier = params.get("_caller_tier")
    target = params.get("agent_id")
    if tier == ADMIN_TIER or caller is None or target is None:
        return
    if caller != target:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


def _check_caller_owns_job(job_agent_id: str, params: dict[str, Any]) -> None:
    """Raise ToolForbiddenError if caller does not own the job's agent_id."""
    caller = params.get("_caller_agent_id")
    tier = params.get("_caller_tier")
    if tier == ADMIN_TIER or caller is None:
        return
    if caller != job_agent_id:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


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
    return {
        "job_id": job.id,
        "status": job.status.value,
        "cost": str(job.cost),
        "created_at": job.created_at,
    }


async def _get_verification_status(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    job = await ctx.gatekeeper_api.get_verification_status(params["job_id"])
    _check_caller_owns_job(job.agent_id, params)
    return {
        "job_id": job.id,
        "agent_id": job.agent_id,
        "status": job.status.value,
        "result": job.result.value if job.result else None,
        "proof_artifact_id": job.proof_artifact_id,
        "cost": str(job.cost),
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
    return {
        "jobs": [
            {
                "job_id": j.id,
                "status": j.status.value,
                "result": j.result.value if j.result else None,
                "cost": str(j.cost),
                "created_at": j.created_at,
            }
            for j in jobs
        ],
        "count": len(jobs),
    }


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
