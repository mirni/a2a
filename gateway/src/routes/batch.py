"""POST /v1/batch — execute multiple tool calls in a single request."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.src.auth import extract_api_key
from gateway.src.catalog import get_tool
from gateway.src.errors import error_response, handle_product_exception
from gateway.src.middleware import Metrics
from gateway.src.routes.execute import _rate_limit_headers, _try_x402_payment, calculate_tool_cost
from gateway.src.tools import TOOL_REGISTRY

logger = logging.getLogger("a2a.batch")

router = APIRouter()

_MAX_BATCH_SIZE = 10


@router.post("/v1/batch")
async def batch(request: Request) -> JSONResponse:
    """Execute multiple tool calls in a single request."""
    # --- Parse body ---
    try:
        body: dict[str, Any] = await request.json()
    except (ValueError, TypeError):
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

    # --- Extract + validate API key (with x402 fallback) ---
    raw_key = extract_api_key(request)
    ctx = request.app.state.ctx
    x402_proof = None
    x402_agent_id = None

    # Pre-calculate total cost for batch (needed for x402 pricing)
    total_cost = 0.0
    for call in calls:
        if not isinstance(call, dict):
            continue
        _tn = call.get("tool")
        if not _tn:
            continue
        _td = get_tool(_tn)
        if _td is None:
            continue
        _tp = _td.get("pricing", {})
        total_cost += calculate_tool_cost(_tp, call.get("params", {}))

    if not raw_key:
        # Try x402 payment as alternative auth for the whole batch
        # Use a synthetic tool_def with total cost for the batch
        batch_tool_def = {"pricing": {"per_call": total_cost}}
        x402_result = await _try_x402_payment(request, ctx, "batch", batch_tool_def)
        if isinstance(x402_result, JSONResponse):
            return x402_result
        if x402_result is None:
            return await error_response(401, "Missing API key", "missing_key", request=request)
        x402_agent_id, x402_proof = x402_result

    if x402_agent_id:
        agent_id = x402_agent_id
        agent_tier = "x402"
    else:
        try:
            key_info = await ctx.key_manager.validate_key(raw_key)
        except Exception as exc:
            return await handle_product_exception(request, exc)

        agent_id = key_info["agent_id"]
        agent_tier = key_info["tier"]

    if not x402_agent_id:
        # --- Global rate limit check (sliding window) ---
        from paywall_src.tiers import get_tier_config

        tier_config = get_tier_config(agent_tier)
        window_key = "gateway"
        try:
            rate_count = await ctx.paywall_storage.get_sliding_window_count(agent_id, window_key, window_seconds=3600.0)
            if rate_count >= tier_config.rate_limit_per_hour:
                burst_count = await ctx.paywall_storage.get_burst_count(agent_id, window_key, burst_window_seconds=60.0)
                burst_limit = tier_config.rate_limit_per_hour // 60 + tier_config.burst_allowance
                if burst_count >= burst_limit:
                    return await error_response(
                        429,
                        f"Rate limit exceeded: {rate_count}/{tier_config.rate_limit_per_hour} per hour",
                        "rate_limit_exceeded",
                        request=request,
                    )
        except (RuntimeError, OSError):
            logger.error("Rate limit check failed for agent %s", agent_id, exc_info=True)
            return await error_response(503, "Rate limit service unavailable", "service_error", request=request)

        # --- Check balance ---
        if total_cost > 0:
            try:
                balance = await ctx.tracker.get_balance(agent_id)
                if balance < total_cost:
                    return await error_response(
                        402,
                        f"Insufficient balance for batch: {balance} < {total_cost} credits required",
                        "insufficient_balance",
                        request=request,
                    )
            except Exception as exc:
                return await handle_product_exception(request, exc)

    # --- Execute each call sequentially ---
    results: list[dict[str, Any]] = []

    for call in calls:
        if not isinstance(call, dict):
            results.append(
                {
                    "success": False,
                    "error": {"code": "bad_request", "message": "Each call must be a JSON object"},
                }
            )
            continue

        tool_name = call.get("tool")
        params = call.get("params", {})

        if not tool_name:
            results.append(
                {
                    "success": False,
                    "error": {"code": "bad_request", "message": "Missing 'tool' field in call"},
                }
            )
            continue

        # Look up tool in catalog
        tool_def = get_tool(tool_name)
        if tool_def is None:
            results.append(
                {
                    "success": False,
                    "error": {"code": "unknown_tool", "message": f"Unknown tool: {tool_name}"},
                }
            )
            continue

        if tool_name not in TOOL_REGISTRY:
            results.append(
                {
                    "success": False,
                    "error": {
                        "code": "not_implemented",
                        "message": f"Tool '{tool_name}' is not implemented",
                    },
                }
            )
            continue

        # Check required parameters
        input_schema = tool_def.get("input_schema", {})
        required_params = input_schema.get("required", [])
        missing = [p for p in required_params if p not in params]
        if missing:
            results.append(
                {
                    "success": False,
                    "error": {
                        "code": "missing_parameter",
                        "message": f"Missing required parameter(s): {', '.join(missing)}",
                    },
                }
            )
            continue

        # Check tier access (skip for x402)
        if not x402_agent_id:
            from paywall_src.tiers import tier_has_access as _tier_check

            required_tier = tool_def.get("tier_required", "free")
            if not _tier_check(agent_tier, required_tier):
                results.append(
                    {
                        "success": False,
                        "error": {
                            "code": "insufficient_tier",
                            "message": f"Tier '{agent_tier}' cannot access '{tool_name}'",
                        },
                    }
                )
                continue

            # Per-tool rate limit check
            tool_rate_limit = tool_def.get("rate_limit_per_hour")
            if tool_rate_limit is not None:
                try:
                    tool_rate_count = await ctx.paywall_storage.get_tool_rate_count(
                        agent_id, tool_name, window_seconds=3600.0
                    )
                    if tool_rate_count >= tool_rate_limit:
                        msg = (
                            f"Per-tool rate limit exceeded for '{tool_name}': "
                            f"{tool_rate_count}/{tool_rate_limit} per hour"
                        )
                        results.append(
                            {
                                "success": False,
                                "error": {"code": "rate_limit_exceeded", "message": msg},
                            }
                        )
                        continue
                except (RuntimeError, OSError):
                    logger.error(
                        "Per-tool rate limit check failed for %s/%s",
                        agent_id,
                        tool_name,
                        exc_info=True,
                    )
                    results.append(
                        {
                            "success": False,
                            "error": {"code": "service_error", "message": "Rate limit service unavailable"},
                        }
                    )
                    continue

        # Dispatch to tool function
        _start = time.time()
        await Metrics.record_request(tool_name)
        tool_func = TOOL_REGISTRY[tool_name]

        try:
            result = await tool_func(ctx, params)
            results.append({"success": True, "result": result})
        except Exception as exc:
            await Metrics.record_error()
            results.append({"success": False, "error": {"code": "execution_error", "message": str(exc)}})
        finally:
            elapsed_ms = (time.time() - _start) * 1000
            await Metrics.record_latency(elapsed_ms)

        # Record usage
        tool_pricing = tool_def.get("pricing", {})
        cost = calculate_tool_cost(tool_pricing, params)
        batch_corr = getattr(request.state, "correlation_id", None) or ""
        batch_idx = len(results) - 1
        # Prefer Idempotency-Key header (appended with index for uniqueness)
        header_idem = request.headers.get("idempotency-key")
        batch_idem = (
            f"{header_idem}:{batch_idx}" if header_idem
            else (f"{batch_corr}:{batch_idx}:{tool_name}" if batch_corr else None)
        )
        try:
            await ctx.tracker.storage.record_usage(
                agent_id=agent_id,
                function=tool_name,
                cost=cost,
                idempotency_key=batch_idem,
            )
            if not x402_agent_id:
                if cost > 0:
                    await ctx.tracker.wallet.charge(agent_id, cost, description=f"gateway:batch:{tool_name}")
                await ctx.paywall_storage.record_rate_event(agent_id, "gateway", tool_name)
        except (RuntimeError, OSError):
            logger.warning("Usage recording failed for batch call %s/%s", agent_id, tool_name, exc_info=True)

    # x402 settlement (fire-and-forget after all calls complete)
    if x402_agent_id and x402_proof is not None:
        ctx.x402_verifier.mark_nonce_used(x402_proof.payload.authorization.nonce)
        try:
            await ctx.x402_verifier.settle_with_facilitator(x402_proof)
        except Exception:
            logger.warning("x402 batch settlement failed for %s", agent_id, exc_info=True)
        try:
            auth = x402_proof.payload.authorization
            await ctx.event_bus.publish(
                "x402.payment_settled",
                "gateway",
                {
                    "nonce": auth.nonce,
                    "network": x402_proof.network,
                    "amount": auth.value,
                    "payer": auth.from_address,
                    "tool": "batch",
                },
            )
        except Exception:
            logger.warning("x402 batch event publish failed", exc_info=True)

    correlation_id = getattr(request.state, "correlation_id", None) or ""
    headers: dict[str, str] = {}
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    # Add rate limit headers (skip for x402)
    if not x402_agent_id:
        from paywall_src.tiers import get_tier_config as _get_tier_config

        _tc = _get_tier_config(agent_tier)
        try:
            rate_count = await ctx.paywall_storage.get_sliding_window_count(agent_id, "gateway", window_seconds=3600.0)
        except (RuntimeError, OSError):
            rate_count = 0
        headers.update(_rate_limit_headers(_tc.rate_limit_per_hour, rate_count))

    return JSONResponse({"results": results}, headers=headers)
