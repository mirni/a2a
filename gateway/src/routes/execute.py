"""POST /execute — the core tool-execution endpoint."""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.src.auth import extract_api_key
from gateway.src.catalog import get_tool
from gateway.src.errors import error_response, handle_product_exception
from gateway.src.tools import TOOL_REGISTRY


async def execute(request: Request) -> JSONResponse:
    """Execute a tool with authentication, tier checks, rate limiting, and billing."""
    # --- Parse body ---
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return await error_response(400, "Invalid JSON body", "bad_request")

    tool_name = body.get("tool")
    params = body.get("params", {})

    if not tool_name:
        return await error_response(400, "Missing 'tool' field", "bad_request")

    # --- 1. Look up tool in catalog ---
    tool_def = get_tool(tool_name)
    if tool_def is None:
        return await error_response(400, f"Unknown tool: {tool_name}", "unknown_tool")

    if tool_name not in TOOL_REGISTRY:
        return await error_response(
            501, f"Tool '{tool_name}' is cataloged but not implemented", "not_implemented"
        )

    # --- 2. Extract + validate API key ---
    raw_key = extract_api_key(request)
    if not raw_key:
        return await error_response(401, "Missing API key", "missing_key")

    ctx = request.app.state.ctx

    try:
        key_info = await ctx.key_manager.validate_key(raw_key)
    except Exception as exc:
        return await handle_product_exception(request, exc)

    agent_id = key_info["agent_id"]
    agent_tier = key_info["tier"]

    # --- 3. Check tier access ---
    from paywall_src.tiers import tier_has_access

    required_tier = tool_def.get("tier_required", "free")
    if not tier_has_access(agent_tier, required_tier):
        return await error_response(
            403,
            f"Tier '{agent_tier}' cannot access tool '{tool_name}' (requires '{required_tier}')",
            "insufficient_tier",
        )

    # --- 4. Check rate limit ---
    from paywall_src.tiers import get_tier_config

    tier_config = get_tier_config(agent_tier)
    window_start = time.time() // 3600 * 3600  # current hour boundary
    window_key = "gateway"
    try:
        rate_count = await ctx.paywall_storage.get_rate_count(
            agent_id, window_key, window_start
        )
        if rate_count >= tier_config.rate_limit_per_hour:
            return await error_response(
                429,
                f"Rate limit exceeded: {rate_count}/{tier_config.rate_limit_per_hour} per hour",
                "rate_limit_exceeded",
            )
    except Exception:
        pass  # If rate counting fails, allow the request

    # --- 5. Check balance if tool costs credits ---
    per_call = tool_def.get("pricing", {}).get("per_call", 0.0)
    if per_call > 0:
        try:
            balance = await ctx.tracker.get_balance(agent_id)
            if balance < per_call:
                return await error_response(
                    402,
                    f"Insufficient balance: {balance} < {per_call} credits required",
                    "insufficient_balance",
                )
        except Exception as exc:
            # WalletNotFoundError → 402
            return await handle_product_exception(request, exc)

    # --- 6. Dispatch to tool function ---
    tool_func = TOOL_REGISTRY[tool_name]
    try:
        result = await tool_func(ctx, params)
    except Exception as exc:
        return await handle_product_exception(request, exc)

    # --- 7. Record usage + charge ---
    try:
        await ctx.tracker.storage.record_usage(
            agent_id=agent_id,
            function=tool_name,
            cost=per_call,
        )
        if per_call > 0:
            await ctx.tracker.wallet.charge(agent_id, per_call, description=f"gateway:{tool_name}")
        # Increment rate counter
        await ctx.paywall_storage.increment_rate_count(
            agent_id, window_key, window_start
        )
    except Exception:
        pass  # Usage recording failure should not fail the request

    # --- 8. Return result ---
    return JSONResponse({
        "success": True,
        "result": result,
        "charged": per_call,
    })


routes = [Route("/execute", execute, methods=["POST"])]
