"""Core dependency: ToolContext + require_tool factory + finalize_response."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from gateway.src.authorization import ADMIN_ONLY_TOOLS, ADMIN_TIER, check_ownership_authorization
from gateway.src.catalog import get_tool
from gateway.src.deps.auth import AuthError, authenticate, check_scopes
from gateway.src.deps.billing import calculate_tool_cost, record_usage_and_charge
from gateway.src.deps.rate_limit import (
    RateLimitError,
    ServiceError,
    TierError,
    build_rate_limit_headers,
    check_rate_limits,
)
from gateway.src.errors import error_response
from gateway.src.tools import TOOL_REGISTRY

logger = logging.getLogger("a2a.deps.tool_context")


@dataclass
class ToolContext:
    """Holds all resolved request context for a tool call."""

    ctx: Any
    agent_id: str
    agent_tier: str
    tool_name: str
    tool_def: dict[str, Any]
    cost: float
    rate_count: int
    correlation_id: str
    request: Request
    key_info: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)


def require_tool(tool_name: str):
    """Factory returning a FastAPI dependency that resolves a ToolContext.

    Chains: catalog lookup -> auth -> scope check -> param validation ->
    ownership -> admin guard -> tier check -> rate limit -> balance check -> cost calc.
    """

    async def _dependency(request: Request) -> ToolContext:
        # 1. Catalog lookup
        tool_def = get_tool(tool_name)
        if tool_def is None:
            resp = await error_response(400, f"Unknown tool: {tool_name}", "unknown_tool", request=request)
            raise _ResponseError(resp)

        if tool_name not in TOOL_REGISTRY:
            resp = await error_response(
                501, f"Tool '{tool_name}' is cataloged but not implemented", "not_implemented", request=request
            )
            raise _ResponseError(resp)

        # 2. Auth
        try:
            agent_id, agent_tier, key_info = await authenticate(request)
        except AuthError as exc:
            from gateway.src.anomaly import detector

            detector.record_auth_failure(getattr(exc, "agent_id", "unknown"))
            resp = await error_response(exc.status, exc.message, exc.code, request=request)
            raise _ResponseError(resp) from exc

        # 3. Scope check
        if key_info is not None:
            try:
                await check_scopes(request, key_info, tool_name, {})
            except AuthError as exc:
                resp = await error_response(exc.status, exc.message, exc.code, request=request)
                raise _ResponseError(resp) from exc

        # 4. Admin-only tools
        if tool_name in ADMIN_ONLY_TOOLS and agent_tier != ADMIN_TIER:
            resp = await error_response(
                403, f"Tool '{tool_name}' requires admin privileges", "admin_only", request=request
            )
            raise _ResponseError(resp)

        # 5. Tier check + rate limit
        ctx = request.app.state.ctx
        rate_count = 0
        try:
            rate_count = await check_rate_limits(ctx, agent_id, agent_tier, tool_name, tool_def)
        except TierError as exc:
            resp = await error_response(403, str(exc), "insufficient_tier", request=request)
            raise _ResponseError(resp) from exc
        except RateLimitError as exc:
            from gateway.src.anomaly import detector

            detector.record_rate_limit_hit(agent_id)
            resp = await error_response(429, str(exc), "rate_limit_exceeded", request=request)
            raise _ResponseError(resp) from exc
        except ServiceError as exc:
            resp = await error_response(503, str(exc), "service_error", request=request)
            raise _ResponseError(resp) from exc

        # 6. Cost calculation + balance check
        # Parse request body for percentage-based pricing (needs "amount" param).
        tool_pricing = tool_def.get("pricing", {})
        cost_params: dict[str, Any] = {}
        if tool_pricing.get("model") == "percentage":
            try:
                body = await request.json()
                if isinstance(body, dict) and "amount" in body:
                    cost_params["amount"] = body["amount"]
            except Exception:
                pass
        cost = calculate_tool_cost(tool_pricing, cost_params)

        if agent_tier != ADMIN_TIER and cost > 0:
            try:
                balance = await ctx.tracker.get_balance(agent_id)
                if balance < cost:
                    resp = await error_response(
                        402,
                        f"Insufficient balance: {balance} < {cost} credits required",
                        "insufficient_balance",
                        request=request,
                    )
                    raise _ResponseError(resp)
            except _ResponseError:
                raise
            except Exception as exc:
                from gateway.src.errors import handle_product_exception

                resp = await handle_product_exception(request, exc)
                raise _ResponseError(resp) from exc

        correlation_id = getattr(request.state, "correlation_id", None) or ""

        return ToolContext(
            ctx=ctx,
            agent_id=agent_id,
            agent_tier=agent_tier,
            tool_name=tool_name,
            tool_def=tool_def,
            cost=cost,
            rate_count=rate_count,
            correlation_id=correlation_id,
            request=request,
            key_info=key_info,
        )

    return _dependency


async def _log_api_call(tc: ToolContext, status_code: int) -> None:
    """Best-effort audit log of every authenticated API call."""
    try:
        db = tc.ctx.tracker.storage.db
        client_ip = tc.request.client.host if tc.request.client else None
        await db.execute(
            "INSERT INTO api_audit_log (timestamp, agent_id, tool_name, method, path, status_code, client_ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                __import__("time").time(),
                tc.agent_id,
                tc.tool_name,
                tc.request.method,
                str(tc.request.url.path),
                status_code,
                client_ip,
            ),
        )
        await db.commit()
    except Exception:
        logger.debug("Failed to write API audit log", exc_info=True)


async def finalize_response(
    tc: ToolContext,
    result: dict[str, Any],
    *,
    status_code: int = 200,
    location: str | None = None,
) -> JSONResponse:
    """Post-call: record usage, serialize response, build headers, return JSONResponse."""
    from gateway.src.middleware import Metrics
    from gateway.src.serialization import serialize_money, serialize_response

    # Record usage + charge
    idem_key = tc.request.headers.get("idempotency-key") or (
        f"{tc.correlation_id}:{tc.tool_name}" if tc.correlation_id else None
    )
    await record_usage_and_charge(tc.ctx, tc.agent_id, tc.tool_name, tc.cost, idem_key, tc.correlation_id)

    # #9: Best-effort API audit trail
    await _log_api_call(tc, status_code)

    # Record metrics
    await Metrics.record_request(tc.tool_name)

    # Serialize
    result = serialize_response(result)

    # Build headers
    headers: dict[str, str] = {}
    if tc.correlation_id:
        headers["X-Request-ID"] = tc.correlation_id

    headers["X-Charged"] = serialize_money(tc.cost)

    # Rate limit headers for non-admin
    if tc.agent_tier != ADMIN_TIER:
        from paywall_src.tiers import get_tier_config

        tier_config = get_tier_config(tc.agent_tier)
        headers.update(build_rate_limit_headers(tier_config.rate_limit_per_hour, tc.rate_count))

    # #21: Key age warning header
    if tc.key_info and tc.key_info.get("_key_age_warning"):
        headers["X-Key-Age-Warning"] = tc.key_info["_key_age_warning"]

    # Location header
    if location:
        headers["Location"] = location

    # Link header for cursor-based pagination
    if isinstance(result, dict) and result.get("has_more") and result.get("next_cursor"):
        cursor = result["next_cursor"]
        limit = result.get("limit", 50)
        link_url = f"?cursor={cursor}&limit={limit}"
        headers["Link"] = f'<{link_url}>; rel="next"'

    # Sign response
    signing_manager = getattr(tc.request.app.state, "signing_manager", None)
    if signing_manager:
        import json as _json

        from gateway.src.signing import sign_response

        body_bytes = _json.dumps(result).encode()
        headers.update(sign_response(signing_manager, body_bytes))

    return JSONResponse(result, status_code=status_code, headers=headers)


async def check_ownership(tc: ToolContext, params: dict[str, Any]) -> None:
    """Verify ownership fields in *params* match the authenticated caller.

    Must be called by route handlers AFTER ``_inject_caller()`` so that
    ``params`` contains the user-supplied fields (``agent_id``, ``payer``,
    ``sender``, etc.).  Raises ``_ResponseError(403)`` on violation.
    Admin-tier agents bypass the check.
    """
    result = check_ownership_authorization(
        caller_agent_id=tc.agent_id,
        caller_tier=tc.agent_tier,
        params=params,
        tool_name=tc.tool_name,
    )
    if result is not None:
        status, message, code = result
        resp = await error_response(status, message, code, request=tc.request)
        raise _ResponseError(resp)


class _ResponseError(Exception):
    """Internal: wraps a JSONResponse to short-circuit dependency resolution."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__()
        self.response = response
