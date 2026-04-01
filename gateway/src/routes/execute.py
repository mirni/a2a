"""POST /execute — the core tool-execution endpoint."""

from __future__ import annotations

import base64
import json
import logging
import math
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from gateway.src.auth import extract_api_key
from gateway.src.authorization import ADMIN_ONLY_TOOLS, ADMIN_TIER, check_ownership_authorization
from gateway.src.catalog import get_tool
from gateway.src.errors import error_response, handle_product_exception
from gateway.src.middleware import Metrics
from gateway.src.tool_errors import X402ReplayError, X402VerificationError
from gateway.src.tools import TOOL_REGISTRY

logger = logging.getLogger("a2a.execute")

router = APIRouter()

_MAX_TOOL_NAME_LEN = 128


class ExecuteRequestBody(BaseModel):
    """Pydantic model for the /v1/execute request body."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    params: dict[str, Any] = {}


def _sanitize_tool_name(name: str) -> str:
    """Strip null bytes and truncate tool name for safe use in messages."""
    name = name.replace("\x00", "")
    if len(name) > _MAX_TOOL_NAME_LEN:
        name = name[:_MAX_TOOL_NAME_LEN]
    return name


async def _log_admin_audit(
    ctx: Any,
    request: Request,
    *,
    agent_id: str,
    tool_name: str,
    params: dict[str, Any],
    status: str,
    result_summary: str | None = None,
) -> None:
    """Log an admin operation to the admin audit log (best-effort)."""
    try:
        from gateway.src.admin_audit import log_admin_operation

        client_ip: str | None = None
        if request.client:
            client_ip = request.client.host
        db = ctx.tracker.storage.db
        await log_admin_operation(
            db=db,
            agent_id=agent_id,
            tool_name=tool_name,
            params=params,
            client_ip=client_ip,
            status=status,
            result_summary=result_summary,
        )
    except Exception:
        logger.warning(
            "Failed to log admin audit for agent=%s tool=%s",
            agent_id,
            tool_name,
            exc_info=True,
        )


def _validate_params(params: dict[str, Any], input_schema: dict[str, Any]) -> str | None:
    """Validate tool params against the catalog's JSON Schema.

    Returns None if valid, or an error message string if invalid.
    Validates types for declared properties. Extra properties are allowed
    since the catalog may not document all accepted params (e.g. internal
    flags like signup_bonus, idempotency_key).
    """
    import jsonschema

    try:
        jsonschema.validate(instance=params, schema=input_schema)
    except jsonschema.ValidationError as exc:
        field = ".".join(str(p) for p in exc.absolute_path) if exc.absolute_path else ""
        if field:
            return f"Invalid parameter '{field}': {exc.message}"
        return f"Parameter validation failed: {exc.message}"
    return None


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
    except Exception as exc:
        logger.error("Facilitator verification error: %s", exc, exc_info=True)
        return await error_response(
            402, f"Facilitator unavailable: {exc}", "payment_verification_failed", request=request
        )

    return (proof.payload.authorization.from_address, proof)


@router.post("/v1/execute")
async def execute(request: Request) -> JSONResponse:
    """Execute a tool with authentication, tier checks, rate limiting, and billing."""
    _start_time = time.time()

    # --- Parse body ---
    try:
        raw_body: dict[str, Any] = await request.json()
    except (ValueError, TypeError):
        return await error_response(400, "Invalid JSON body", "bad_request", request=request)

    if not isinstance(raw_body, dict):
        return await error_response(400, "Request body must be a JSON object", "bad_request", request=request)

    try:
        body = ExecuteRequestBody.model_validate(raw_body)
    except ValidationError as ve:
        # Distinguish extra-field errors (422) from missing-field errors (400).
        has_extra = any(e["type"] == "extra_forbidden" for e in ve.errors())
        if has_extra:
            return await error_response(422, "Extra fields are not allowed", "validation_error", request=request)
        # Missing 'tool' or wrong types → fall through to legacy handling below
        body = None

    tool_name: str | None
    if body is not None:
        tool_name = _sanitize_tool_name(body.tool)
        params = body.params
    else:
        tool_name_raw = raw_body.get("tool")
        tool_name = _sanitize_tool_name(tool_name_raw) if isinstance(tool_name_raw, str) else None
        params = raw_body.get("params", {})

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

    # --- 2. Extract + validate API key (with x402 fallback) ---
    # Auth MUST run before param validation to avoid leaking schema info
    # (required parameter names) to unauthenticated callers.
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

        # Promote effective tier to admin when the key carries an admin scope.
        # This ensures admin-scoped keys can use admin-only tools regardless
        # of their nominal tier.
        key_scopes = key_info.get("scopes", ["read", "write"])
        if "admin" in key_scopes:
            agent_tier = ADMIN_TIER

        # --- 2a. Enforce key scoping (allowed_tools, allowed_agent_ids, scopes) ---
        from paywall_src.scoping import KeyScopeError, ScopeChecker

        scope_checker = ScopeChecker(
            scopes=key_info.get("scopes", ["read", "write"]),
            allowed_tools=key_info.get("allowed_tools"),
            allowed_agent_ids=key_info.get("allowed_agent_ids"),
        )
        try:
            scope_checker.check_tool(tool_name)
            scope_checker.check_scope(tool_name)
            # Check agent_id param if present — skip for tools where
            # agent_id is a target reference rather than caller identity
            # (e.g. trust tools use agent_id as alias for server_id).
            from gateway.src.authorization import AGENT_ID_IS_TARGET

            target_agent = params.get("agent_id")
            if target_agent is not None and tool_name not in AGENT_ID_IS_TARGET:
                scope_checker.check_agent_id(target_agent)
        except KeyScopeError as exc:
            return await error_response(403, exc.reason, "scope_violation", request=request)

    # --- 2b. Validate required parameters (after auth) ---
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

    # --- 2b-2. Validate parameter types against input_schema ---
    if input_schema:
        validation_error = _validate_params(params, input_schema)
        if validation_error is not None:
            return await error_response(
                422,
                validation_error,
                "invalid_parameter",
                request=request,
            )

    # --- 2b-3. Ownership authorization: caller must own the resource ---
    authz_result = check_ownership_authorization(agent_id, agent_tier, params, tool_name=tool_name)
    if authz_result is not None:
        status, message, code = authz_result
        return await error_response(status, message, code, request=request)

    # --- 2c. Admin-only tools: block non-admin callers ---
    if tool_name in ADMIN_ONLY_TOOLS and agent_tier != ADMIN_TIER:
        # Log denied admin tool attempt
        await _log_admin_audit(ctx, request, agent_id=agent_id, tool_name=tool_name, params=params, status="denied")
        return await error_response(
            403,
            f"Tool '{tool_name}' requires admin privileges",
            "admin_only",
            request=request,
        )

    # --- 3. Check tier access (skip for x402) ---
    tool_pricing = tool_def.get("pricing", {})
    cost = calculate_tool_cost(tool_pricing, params)
    rate_count = 0

    if not x402_agent_id and agent_tier != ADMIN_TIER:
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
            rate_count = await ctx.paywall_storage.get_sliding_window_count(agent_id, window_key, window_seconds=3600.0)
            if rate_count >= tier_config.rate_limit_per_hour:
                # Check burst allowance (1-minute window)
                burst_count = await ctx.paywall_storage.get_burst_count(agent_id, window_key, burst_window_seconds=60.0)
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
            return await error_response(503, "Rate limit service unavailable", "service_error", request=request)

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

    # --- 6. Dispatch to tool function ---
    # Inject caller identity so tools can perform ownership checks
    params["_caller_agent_id"] = agent_id
    params["_caller_tier"] = agent_tier

    # Record the request in metrics regardless of outcome
    await Metrics.record_request(tool_name)

    tool_func = TOOL_REGISTRY[tool_name]
    try:
        result = await tool_func(ctx, params)
    except Exception as exc:
        # Log admin tool errors
        if tool_name in ADMIN_ONLY_TOOLS:
            await _log_admin_audit(
                ctx,
                request,
                agent_id=agent_id,
                tool_name=tool_name,
                params=params,
                status="error",
                result_summary=str(exc)[:500],
            )
        await Metrics.record_error()
        elapsed_ms = (time.time() - _start_time) * 1000
        await Metrics.record_latency(elapsed_ms)
        return await handle_product_exception(request, exc)

    # Log successful admin tool calls
    if tool_name in ADMIN_ONLY_TOOLS:
        result_summary = str(result)[:500] if result is not None else None
        await _log_admin_audit(
            ctx,
            request,
            agent_id=agent_id,
            tool_name=tool_name,
            params=params,
            status="success",
            result_summary=result_summary,
        )

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
                    logger.warning("x402 settlement failed for %s, queued for retry", agent_id, exc_info=True)
                    ctx.x402_verifier.queue_failed_settlement(x402_proof)
                # Publish settlement event
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
                            "tool": tool_name,
                        },
                    )
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
    await Metrics.record_latency(elapsed_ms)

    # --- 9. Return result ---
    headers: dict[str, str] = {}
    if correlation_id:
        headers["X-Request-ID"] = correlation_id

    # Add rate limit headers (skip for x402 and admin)
    if not x402_agent_id and agent_tier != ADMIN_TIER:
        from paywall_src.tiers import get_tier_config as _get_tier_config

        _tc = _get_tier_config(agent_tier)
        headers.update(_rate_limit_headers(_tc.rate_limit_per_hour, rate_count))

    # Envelope-free: result is the body; cost goes in X-Charged header
    headers["X-Charged"] = str(cost)

    # Sign response if signing manager available
    signing_manager = getattr(request.app.state, "signing_manager", None)
    if signing_manager:
        import json as _json

        from gateway.src.signing import sign_response

        body_bytes = _json.dumps(result).encode()
        headers.update(sign_response(signing_manager, body_bytes))

    return JSONResponse(result, headers=headers)
