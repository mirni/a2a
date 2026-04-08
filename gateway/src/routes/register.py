"""POST /v1/register — Self-service agent registration.

Creates a free-tier API key + wallet with signup bonus.
No authentication required (chicken-and-egg problem).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.errors import error_response

logger = logging.getLogger("a2a.register")

router = APIRouter()


class RegisterRequestBody(BaseModel):
    """Request body for POST /v1/register."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"agent_id": "my-agent-001"}})

    agent_id: str = Field(min_length=1, max_length=128)


@router.post("/v1/register")
async def register(request: Request) -> JSONResponse:
    """Register a new agent: create wallet + free-tier API key."""
    try:
        raw_body = await request.json()
    except (ValueError, TypeError):
        return await error_response(400, "Invalid JSON body", "bad_request", request=request)

    if not isinstance(raw_body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request", request=request)

    # Validate with Pydantic model (extra="forbid" rejects unknown fields)
    try:
        body = RegisterRequestBody(**raw_body)
    except Exception:
        return await error_response(400, "Invalid request body", "bad_request", request=request)

    agent_id = body.agent_id
    if not agent_id:
        return await error_response(400, "Missing required field: agent_id", "bad_request", request=request)

    ctx = request.app.state.ctx

    # Create wallet (with signup bonus)
    try:
        wallet = await ctx.tracker.wallet.create(agent_id, signup_bonus=True)
    except ValueError:
        return await error_response(409, f"Agent '{agent_id}' is already registered", "already_exists", request=request)

    # Create free-tier API key
    try:
        key_info = await ctx.key_manager.create_key(agent_id, tier="free")
    except Exception:
        # nosemgrep: python-logger-credential-disclosure
        logger.exception("Failed to create API key for agent %s", agent_id)
        return await error_response(
            500, "Failed to create API key during registration", "internal_error", request=request
        )

    try:
        balance = float(wallet.get("balance", 0)) if isinstance(wallet, dict) else 0.0
    except (TypeError, ValueError):
        balance = 0.0

    # Auto-register cryptographic identity (best-effort, non-blocking)
    identity_registered = False
    public_key = None
    try:
        identity = await ctx.identity_api.register_agent(agent_id=agent_id)
        identity_registered = True
        public_key = identity.public_key
    except Exception:
        logger.warning("Auto identity registration failed for %s", agent_id)

    logger.info("Agent registered: %s (identity=%s)", agent_id, identity_registered)

    return JSONResponse(
        {
            "agent_id": agent_id,
            "api_key": key_info["key"],
            "tier": "free",
            "balance": balance,
            "identity_registered": identity_registered,
            "public_key": public_key,
            "next_steps": {
                "onboarding": "/v1/onboarding",
                "docs": "/docs",
                "pricing": "/v1/pricing",
            },
        },
        status_code=201,
    )
