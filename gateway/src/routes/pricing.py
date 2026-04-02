"""Pricing / catalog endpoints."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from shared_src.pricing_config import load_pricing_config

from gateway.src.catalog import get_catalog, get_tool
from gateway.src.errors import error_response
from gateway.src.rate_limit_headers import public_rate_limit_headers

_pricing = load_pricing_config()

router = APIRouter()


@router.get("/v1/pricing")
async def pricing_list(request: Request) -> JSONResponse:
    """Return the tool catalog with optional pagination.

    Query params:
        limit (int, optional): Max number of tools to return. Negative values ignored.
        offset (int, optional): Number of tools to skip. Default 0.
        cursor (str, optional): Opaque cursor from previous page's next_cursor.
    """
    from gateway.src.tools._pagination import decode_cursor, encode_cursor

    catalog = get_catalog()
    total = len(catalog)

    # Parse pagination params — cursor takes precedence over offset
    cursor_str = request.query_params.get("cursor")
    limit_str = request.query_params.get("limit")
    offset_str = request.query_params.get("offset")

    if cursor_str:
        offset = decode_cursor(cursor_str)
    else:
        offset = max(0, int(offset_str)) if offset_str else 0

    if limit_str is not None:
        limit_val = int(limit_str)
        if limit_val < 0:
            limit_val = total  # negative → return all
    else:
        limit_val = total  # no limit → return all

    tools = catalog[offset : offset + limit_val]
    has_more = (offset + limit_val) < total

    # Use actual IP-based remaining count when the public rate limiter is active
    limiter = getattr(request.state, "public_rate_limiter", None)
    client_ip = getattr(request.state, "client_ip", None)

    resp_headers = public_rate_limit_headers(limiter=limiter, client_ip=client_ip)

    body: dict = {
        "tools": tools,
        "total": total,
        "limit": limit_val,
        "offset": offset,
        "has_more": has_more,
    }

    if has_more:
        next_cursor = encode_cursor(offset + limit_val)
        body["next_cursor"] = next_cursor
        resp_headers["Link"] = f'</v1/pricing?cursor={next_cursor}&limit={limit_val}>; rel="next"'

    return JSONResponse(body, headers=resp_headers)


@router.get("/v1/pricing/summary")
async def pricing_summary(request: Request) -> JSONResponse:
    """Return pricing grouped by service for a quick overview."""
    catalog = get_catalog()
    by_service: dict[str, list[dict]] = defaultdict(list)
    for tool in catalog:
        svc = tool.get("service", "unknown")
        by_service[svc].append(
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "pricing": tool.get("pricing", {}),
                "tier_required": tool.get("tier_required", "free"),
            }
        )

    services = []
    for svc_name in sorted(by_service.keys()):
        tools = by_service[svc_name]
        services.append(
            {
                "service": svc_name,
                "tool_count": len(tools),
                "tools": tools,
            }
        )

    return JSONResponse({"services": services})


@router.get("/v1/pricing/tiers")
async def pricing_tiers(request: Request) -> JSONResponse:
    """Return a human-readable comparison of all API tiers."""
    plans_by_tier: dict[str, dict | None] = {}
    for plan_name, plan in _pricing.subscription_plans.items():
        plans_by_tier[plan["tier"]] = {
            "plan": plan_name,
            "price_cents": plan.get("price_cents") or plan.get("price_cents_min"),
            "credits_included": plan.get("credits_included"),
            "billing_period": plan.get("billing_period", "monthly"),
        }

    tiers = []
    for name, vals in _pricing.tiers.items():
        tiers.append(
            {
                "name": name,
                "description": vals.get("description", ""),
                "rate_limit_per_hour": vals["rate_limit_per_hour"],
                "burst_allowance": vals.get("burst_allowance", 0),
                "support_level": vals.get("support_level", "none"),
                "audit_log_retention_days": vals.get("audit_log_retention_days"),
                "subscription": plans_by_tier.get(name),
            }
        )

    return JSONResponse({"tiers": tiers})


@router.get("/v1/pricing/{tool}")
async def pricing_detail(request: Request) -> JSONResponse:
    """Return pricing info for a single tool."""
    tool_name = request.path_params["tool"]
    tool = get_tool(tool_name)
    if tool is None:
        return await error_response(404, f"Unknown tool: {tool_name}", "tool_not_found", request=request)
    return JSONResponse({"tool": tool})
