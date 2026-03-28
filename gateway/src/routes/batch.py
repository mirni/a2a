"""POST /v1/batch — execute multiple tool calls in a single request."""

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
from gateway.src.routes.execute import calculate_tool_cost
from gateway.src.tools import TOOL_REGISTRY

_MAX_BATCH_SIZE = 10


async def batch(request: Request) -> JSONResponse:
    """Execute multiple tool calls in a single request."""
    # --- Parse body ---
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return await error_response(400, "Invalid JSON body", "bad_request", request=request)

    if not isinstance(body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request", request=request)

    calls = body.get("calls")
    if calls is None:
        return await error_response(400, "Missing 'calls' field", "bad_request", request=request)

    if not isinstance(calls, list):
        return await error_response(400, "'calls' must be an array", "bad_request", request=request)

    if len(calls) > _MAX_BATCH_SIZE:
        return await error_response(
            400,
            f"Batch size exceeds maximum of {_MAX_BATCH_SIZE} calls",
            "batch_too_large",
            request=request,
        )

    # --- Extract + validate API key ---
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

    # --- Execute each call sequentially ---
    results: list[dict[str, Any]] = []

    for call in calls:
        if not isinstance(call, dict):
            results.append({"success": False, "error": "Each call must be a JSON object"})
            continue

        tool_name = call.get("tool")
        params = call.get("params", {})

        if not tool_name:
            results.append({"success": False, "error": "Missing 'tool' field in call"})
            continue

        # Look up tool in catalog
        tool_def = get_tool(tool_name)
        if tool_def is None:
            results.append({"success": False, "error": f"Unknown tool: {tool_name}"})
            continue

        if tool_name not in TOOL_REGISTRY:
            results.append({"success": False, "error": f"Tool '{tool_name}' is not implemented"})
            continue

        # Check required parameters
        input_schema = tool_def.get("input_schema", {})
        required_params = input_schema.get("required", [])
        missing = [p for p in required_params if p not in params]
        if missing:
            results.append({
                "success": False,
                "error": f"Missing required parameter(s): {', '.join(missing)}",
            })
            continue

        # Check tier access
        from paywall_src.tiers import tier_has_access
        required_tier = tool_def.get("tier_required", "free")
        if not tier_has_access(agent_tier, required_tier):
            results.append({
                "success": False,
                "error": f"Tier '{agent_tier}' cannot access tool '{tool_name}'",
            })
            continue

        # Dispatch to tool function
        _start = time.time()
        Metrics.record_request(tool_name)
        tool_func = TOOL_REGISTRY[tool_name]

        try:
            result = await tool_func(ctx, params)
            results.append({"success": True, "result": result})
        except Exception as exc:
            Metrics.record_error()
            results.append({"success": False, "error": str(exc)})
        finally:
            elapsed_ms = (time.time() - _start) * 1000
            Metrics.record_latency(elapsed_ms)

        # Record usage
        tool_pricing = tool_def.get("pricing", {})
        cost = calculate_tool_cost(tool_pricing, params)
        try:
            await ctx.tracker.storage.record_usage(
                agent_id=agent_id,
                function=tool_name,
                cost=cost,
            )
            if cost > 0:
                await ctx.tracker.wallet.charge(agent_id, cost, description=f"gateway:batch:{tool_name}")
        except Exception:
            pass

    correlation_id = getattr(request.state, "correlation_id", None) or ""
    headers: dict[str, str] = {}
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    return JSONResponse({"results": results}, headers=headers)


routes = [Route("/v1/batch", batch, methods=["POST"])]
