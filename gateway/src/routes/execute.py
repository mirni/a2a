"""POST /execute — the core tool-execution endpoint."""

from __future__ import annotations

import base64
import json
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
from gateway.src.tool_errors import X402ReplayError, X402VerificationError
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
    from gateway.src.tool_errors import NegativeCostError

    model = pricing.get("model")
    if model == "percentage":
        amount = float(params.get("amount", 0))
        pct = float(pricing.get("percentage", 0))
        min_fee = float(pricing.get("min_fee", 0))
        max_fee = float(pricing.get("max_fee", float("inf")))
        raw_fee = amount * pct / 100.0
        cost = max(min_fee, min(max_fee, raw_fee))
        if cost < 0:
            raise NegativeCostError(f"Negative cost calculated: {cost}")
        return cost
    # Flat per-call pricing (default)
    return max(0.0, float(pricing.get("per_call", 0.0)))


async def _try_x402_payment(
    request: Request,
    ctx: Any,
    tool_name: str,
    tool_def: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> JSONResponse | tuple[str, Any] | None:
    """Try x402 payment as alternative auth when no API key is present.

    Returns:
        JSONResponse: 402 or error to return immediately.
        tuple[str, proof]: (agent_id, X402PaymentProof) on success.
        None: x402 not enabled, fall through to normal 401.
    """
    verifier = getattr(ctx, "x402_verifier", None)
    if verifier is None:
        return None

    from gateway.src.x402 import X402PaymentProof

    if params is None:
        params = {}

    payment_header = request.headers.get("x-payment")
    if not payment_header:
        # Build 402 response with payment requirements
        tool_pricing = tool_def.get("pricing", {})
        cost = calculate_tool_cost(tool_pricing, params)
        cost_value = str(int(cost * 1_000_000)) if cost > 0 else "0"
        req = verifier.build_payment_required(
            cost_value=cost_value,
            resource=request.url.path,
        )
        pr_b64 = base64.b64encode(req.model_dump_json().encode()).decode()
        resp = await error_response(
            402, "Payment required — attach X-PAYMENT header", "payment_required", request=request
        )
        resp.headers["payment-required"] = pr_b64
        return resp

    # Decode and validate proof
    try:
        proof_bytes = base64.b64decode(payment_header)
        proof_dict = json.loads(proof_bytes)
        proof = X402PaymentProof.model_validate(proof_dict)
    except Exception:
        return await error_response(
            402, "Invalid X-PAYMENT header encoding", "payment_verification_failed", request=request
        )

    # Calculate cost and convert to USDC smallest units
    tool_pricing = tool_def.get("pricing", {})
    cost = calculate_tool_cost(tool_pricing, params)
    cost_value = str(int(cost * 1_000_000)) if cost > 0 else "0"

    # Local validation
    try:
        verifier.validate_proof_locally(proof, cost_value)
    except X402ReplayError as exc:
        return await error_response(402, str(exc), "payment_replay_detected", request=request)
    except X402VerificationError as exc:
        return await error_response(402, str(exc), "payment_verification_failed", request=request)

    # Facilitator verification
    try:
        await verifier.verify_with_facilitator(proof)
    except X402VerificationError as exc:
        return await error_response(402, str(exc), "payment_verification_failed", request=request)

    return (proof.payload.authorization.from_address, proof)


async def execute(request: Request) -> JSONResponse:
    """Execute a tool with authentication, tier checks, rate limiting, and billing."""
    _start_time = time.time()

    # --- Parse body ---
    try:
        body: dict[str, Any] = await request.json()
    except (ValueError, TypeError):
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

    # --- 2. Extract + validate API key (with x402 fallback) ---
    raw_key = extract_api_key(request)
    ctx = request.app.state.ctx
    x402_proof = None
    x402_agent_id = None

    if not raw_key:
        # Try x402 payment as alternative auth
        x402_result = await _try_x402_payment(request, ctx, tool_name, tool_def, params)
        if isinstance(x402_result, JSONResponse):
            return x402_result  # 402 or error response
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

    # --- 3. Check tier access (skip for x402) ---
    tool_pricing = tool_def.get("pricing", {})
    cost = calculate_tool_cost(tool_pricing, params)
    rate_count = 0

    if not x402_agent_id:
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
        except (RuntimeError, OSError):
            logger.error("Rate limit check failed for agent %s", agent_id, exc_info=True)
            return await error_response(
                503, "Rate limit service unavailable", "service_error", request=request
            )

        # --- 5. Check balance if tool costs credits ---
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
    correlation_id = getattr(request.state, "correlation_id", None) or ""
    idem_key = f"{correlation_id}:{tool_name}" if correlation_id else None
    try:
        await ctx.tracker.storage.record_usage(
            agent_id=agent_id,
            function=tool_name,
            cost=cost,
            idempotency_key=idem_key,
        )
        if x402_agent_id:
            # x402: mark nonce used + fire-and-forget settlement
            if x402_proof is not None:
                ctx.x402_verifier.mark_nonce_used(x402_proof.payload.authorization.nonce)
                try:
                    await ctx.x402_verifier.settle_with_facilitator(x402_proof)
                except Exception:
                    logger.warning("x402 settlement failed for %s", agent_id, exc_info=True)
                # Publish settlement event
                try:
                    auth = x402_proof.payload.authorization
                    await ctx.event_bus.publish("x402.payment_settled", "gateway", {
                        "nonce": auth.nonce,
                        "network": x402_proof.network,
                        "amount": auth.value,
                        "payer": auth.from_address,
                        "tool": tool_name,
                    })
                except Exception:
                    logger.warning("x402 event publish failed", exc_info=True)
        else:
            if cost > 0:
                await ctx.tracker.wallet.charge(agent_id, cost, description=f"gateway:{tool_name}")
            # Record rate event for sliding window tracking
            await ctx.paywall_storage.record_rate_event(agent_id, "gateway", tool_name)
    except (RuntimeError, OSError):
        logger.warning("Usage recording failed for agent %s, tool %s", agent_id, tool_name, exc_info=True)

    # --- 8. Record latency ---
    elapsed_ms = (time.time() - _start_time) * 1000
    Metrics.record_latency(elapsed_ms)

    # --- 9. Return result ---
    headers: dict[str, str] = {}
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    # Add rate limit headers (skip for x402)
    if not x402_agent_id:
        from paywall_src.tiers import get_tier_config as _get_tier_config
        _tc = _get_tier_config(agent_tier)
        headers.update(_rate_limit_headers(_tc.rate_limit_per_hour, rate_count))

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
