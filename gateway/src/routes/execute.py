"""POST /execute — the core tool-execution endpoint."""

from __future__ import annotations

import logging
import math
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

logger = logging.getLogger("a2a.execute")


def _rate_limit_headers(limit: int, rate_count: int, window_seconds: float = 3600.0) -> dict[str, str]:
    """Build X-RateLimit-* headers."""
    remaining = max(0, limit - rate_count)
    reset = max(1, math.ceil(window_seconds - (time.time() % window_seconds)))
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }


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
        return await error_response(400, "Invalid JSON body", "bad_request", request=request)

    if not isinstance(body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request", request=request)

    tool_name = body.get("tool")
    params = body.get("params", {})

    if not tool_name:
        return await error_response(400, "Missing 'tool' field", "bad_request", request=request)

    # --- 1. Look up tool in catalog ---
    tool_def = get_tool(tool_name)
    if tool_def is None:
        return await error_response(400, f"Unknown tool: {tool_name}", "unknown_tool", request=request)

    if tool_name not in TOOL_REGISTRY:
        return await error_response(
            501, f"Tool '{tool_name}' is cataloged but not implemented", "not_implemented", request=request
        )

    # --- 1b. Validate required parameters ---
    input_schema = tool_def.get("input_schema", {})
    required_params = input_schema.get("required", [])
    missing = [p for p in required_params if p not in params]
    if missing:
        return await error_response(
            400,
            f"Missing required parameter(s): {', '.join(missing)}",
            "missing_parameter",
            request=request,
        )

    # --- 2. Extract + validate API key ---
    raw_key = extract_api_key(request)
    if not raw_key:
        return await error_response(401, "Missing API key", "missing_key", request=request)

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
            request=request,
        )

    # --- 4. Check rate limit (sliding window) ---
    from paywall_src.tiers import get_tier_config

    tier_config = get_tier_config(agent_tier)
    window_key = "gateway"
    rate_count = 0
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
                rl_headers = _rate_limit_headers(tier_config.rate_limit_per_hour, rate_count)
                resp = await error_response(
                    429,
                    f"Rate limit exceeded: {rate_count}/{tier_config.rate_limit_per_hour} per hour",
                    "rate_limit_exceeded",
                    request=request,
                )
                resp.headers.update(rl_headers)
                return resp

        # Per-tool rate limit check (if defined in catalog)
        tool_rate_limit = tool_def.get("rate_limit_per_hour")
        if tool_rate_limit is not None:
            tool_rate_count = await ctx.paywall_storage.get_tool_rate_count(
                agent_id, tool_name, window_seconds=3600.0
            )
            if tool_rate_count >= tool_rate_limit:
                rl_headers = _rate_limit_headers(tier_config.rate_limit_per_hour, rate_count)
                resp = await error_response(
                    429,
                    f"Per-tool rate limit exceeded for '{tool_name}': {tool_rate_count}/{tool_rate_limit} per hour",
                    "rate_limit_exceeded",
                    request=request,
                )
                resp.headers.update(rl_headers)
                return resp
    except Exception:
        logger.error("Rate limit check failed for agent %s", agent_id, exc_info=True)
        return await error_response(
            503, "Rate limit service unavailable", "service_error", request=request
        )

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
                    request=request,
                )
        except Exception as exc:
            # WalletNotFoundError → 402
            return await handle_product_exception(request, exc)

    # --- 5b. Tool-specific authorization checks ---
    if tool_name == "create_api_key":
        requested_agent = params.get("agent_id", "")
        if requested_agent != agent_id and agent_tier != "admin":
            return await error_response(
                403,
                f"Cannot create API key for agent '{requested_agent}' (you are '{agent_id}')",
                "forbidden",
                request=request,
            )

    # --- 6. Dispatch to tool function ---
    # Record the request in metrics regardless of outcome
    Metrics.record_request(tool_name)

    tool_func = TOOL_REGISTRY[tool_name]
    try:
        result = await tool_func(ctx, params)
    except Exception as exc:
        Metrics.record_error()
        elapsed_ms = (time.time() - _start_time) * 1000
        Metrics.record_latency(elapsed_ms)
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
        logger.warning("Usage recording failed for agent %s, tool %s", agent_id, tool_name, exc_info=True)

    # --- 8. Record latency ---
    elapsed_ms = (time.time() - _start_time) * 1000
    Metrics.record_latency(elapsed_ms)

    # --- 9. Return result ---
    headers: dict[str, str] = {}
    correlation_id = getattr(request.state, "correlation_id", None) or ""
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    # Add rate limit headers
    headers.update(_rate_limit_headers(tier_config.rate_limit_per_hour, rate_count))

    response_body: dict[str, Any] = {
        "success": True,
        "result": result,
        "charged": cost,
        "request_id": correlation_id,
    }

    # Sign response if signing manager available
    signing_manager = getattr(request.app.state, "signing_manager", None)
    if signing_manager:
        from gateway.src.signing import sign_response
        import json as _json

        body_bytes = _json.dumps({"success": True, "result": result, "charged": cost}).encode()
        headers.update(sign_response(signing_manager, body_bytes))

    return JSONResponse(response_body, headers=headers)


routes = [Route("/v1/execute", execute, methods=["POST"])]
