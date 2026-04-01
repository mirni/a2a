"""POST /v1/register — Self-service agent registration.

Creates a free-tier API key + wallet with signup bonus.
No authentication required (chicken-and-egg problem).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from gateway.src.errors import error_response

logger = logging.getLogger("a2a.register")

router = APIRouter()


class RegisterRequestBody(BaseModel):
    """Request body for POST /v1/register."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str


@router.post("/v1/register")
async def register(request: Request) -> JSONResponse:
    """Register a new agent: create wallet + free-tier API key."""
    try:
        raw_body = await request.json()
    except (ValueError, TypeError):
        return await error_response(400, "Invalid JSON body", "bad_request", request=request)

    if not isinstance(raw_body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request", request=request)

    agent_id = raw_body.get("agent_id")
    if not agent_id or not isinstance(agent_id, str):
        return await error_response(400, "Missing required field: agent_id", "bad_request", request=request)

    ctx = request.app.state.ctx

    # Create wallet (with signup bonus)
    try:
        wallet = await ctx.tracker.wallet.create(agent_id, signup_bonus=True)
    except ValueError:
        return await error_response(409, f"Agent '{agent_id}' is already registered", "already_exists", request=request)

    # Create free-tier API key
    key_info = await ctx.key_manager.create_key(agent_id, tier="free")

    balance = float(wallet.get("balance", 0)) if isinstance(wallet, dict) else 0.0

    logger.info("Agent registered: %s", agent_id)

    return JSONResponse(
        {
            "agent_id": agent_id,
            "api_key": key_info["key"],
            "tier": "free",
            "balance": balance,
        },
        status_code=201,
    )
