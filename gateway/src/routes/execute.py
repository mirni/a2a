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
from gateway.src.middleware import Metrics
from gateway.src.tools import TOOL_REGISTRY


def calculate_tool_cost(pricing: dict[str, Any], params: dict[str, Any]) -> float:
    """Calculate the cost of a tool call based on the pricing model.

    Supports two pricing models:
    - "percentage": fee = clamp(amount * percentage / 100, min_fee, max_fee)
    - flat (default): fee = pricing["per_call"]
    """
    model = pricing.get("model")
    if model == "percentage":
        amount = float(params.get("amount", 0))
        pct = float(pricing.get("percentage", 0))
        min_fee = float(pricing.get("min_fee", 0))
        max_fee = float(pricing.get("max_fee", float("inf")))
        raw_fee = amount * pct / 100.0
        return max(min_fee, min(max_fee, raw_fee))
    # Flat per-call pricing (default)
    return float(pricing.get("per_call", 0.0))


async def execute(request: Request) -> JSONResponse:
    """Execute a tool with authentication, tier checks, rate limiting, and billing."""
    _start_time = time.time()

    # --- Parse body ---
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return await error_response(400, "Invalid JSON body", "bad_request")

    if not isinstance(body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request")

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

    # --- 4. Check rate limit (sliding window) ---
    from paywall_src.tiers import get_tier_config

    tier_config = get_tier_config(agent_tier)
    window_key = "gateway"
    try:
        # Global sliding window check (1 hour)
        rate_count = await ctx.paywall_storage.get_sliding_window_count(
            agent_id, window_key, window_seconds=3600.0
        )
        if rate_count >= tier_config.rate_limit_per_hour:
            # Check burst allowance (1-minute window)
            burst_count = await ctx.paywall_storage.get_burst_count(
                agent_id, window_key, burst_window_seconds=60.0
            )
            burst_limit = tier_config.rate_limit_per_hour // 60 + tier_config.burst_allowance
            if burst_count >= burst_limit:
                return await error_response(
                    429,
                    f"Rate limit exceeded: {rate_count}/{tier_config.rate_limit_per_hour} per hour",
                    "rate_limit_exceeded",
                )

        # Per-tool rate limit check (if defined in catalog)
        tool_rate_limit = tool_def.get("rate_limit_per_hour")
        if tool_rate_limit is not None:
            tool_rate_count = await ctx.paywall_storage.get_tool_rate_count(
                agent_id, tool_name, window_seconds=3600.0
            )
            if tool_rate_count >= tool_rate_limit:
                return await error_response(
                    429,
                    f"Per-tool rate limit exceeded for '{tool_name}': {tool_rate_count}/{tool_rate_limit} per hour",
                    "rate_limit_exceeded",
                )
    except Exception:
        pass  # If rate counting fails, allow the request

    # --- 5. Check balance if tool costs credits ---
    tool_pricing = tool_def.get("pricing", {})
    cost = calculate_tool_cost(tool_pricing, params)
    if cost > 0:
        try:
            balance = await ctx.tracker.get_balance(agent_id)
            if balance < cost:
                return await error_response(
                    402,
                    f"Insufficient balance: {balance} < {cost} credits required",
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
        Metrics.record_error()
        return await handle_product_exception(request, exc)

    # --- 7. Record usage + charge ---
    try:
        await ctx.tracker.storage.record_usage(
            agent_id=agent_id,
            function=tool_name,
            cost=cost,
        )
        if cost > 0:
            await ctx.tracker.wallet.charge(agent_id, cost, description=f"gateway:{tool_name}")
        # Record rate event for sliding window tracking
        await ctx.paywall_storage.record_rate_event(agent_id, window_key, tool_name)
    except Exception:
        pass  # Usage recording failure should not fail the request

    # --- 8. Record metrics ---
    Metrics.record_request(tool_name)
    elapsed_ms = (time.time() - _start_time) * 1000
    Metrics.record_latency(elapsed_ms)

    # --- 9. Return result ---
    headers: dict[str, str] = {}
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    # Sign response if signing manager available
    signing_manager = getattr(request.app.state, "signing_manager", None)
    if signing_manager:
        from gateway.src.signing import sign_response
        import json as _json

        body_bytes = _json.dumps({"success": True, "result": result, "charged": cost}).encode()
        headers.update(sign_response(signing_manager, body_bytes))

    return JSONResponse(
        {"success": True, "result": result, "charged": cost},
        headers=headers,
    )


routes = [Route("/v1/execute", execute, methods=["POST"])]
