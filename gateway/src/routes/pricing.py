"""Pricing / catalog endpoints."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.src.catalog import get_catalog, get_tool
from gateway.src.rate_limit_headers import public_rate_limit_headers

router = APIRouter()


@router.get("/v1/pricing")
async def pricing_list(request: Request) -> JSONResponse:
    """Return the tool catalog with optional pagination.

    Query params:
        limit (int, optional): Max number of tools to return. Negative values ignored.
        offset (int, optional): Number of tools to skip. Default 0.
    """
    catalog = get_catalog()
    total = len(catalog)

    # Parse pagination params
    limit_str = request.query_params.get("limit")
    offset_str = request.query_params.get("offset")

    offset = max(0, int(offset_str)) if offset_str else 0
    if limit_str is not None:
        limit_val = int(limit_str)
        if limit_val < 0:
            limit_val = total  # negative → return all
    else:
        limit_val = total  # no limit → return all

    tools = catalog[offset : offset + limit_val]

    # Use actual IP-based remaining count when the public rate limiter is active
    limiter = getattr(request.state, "public_rate_limiter", None)
    client_ip = getattr(request.state, "client_ip", None)

    return JSONResponse(
        {
            "tools": tools,
            "total": total,
            "limit": limit_val,
            "offset": offset,
        },
        headers=public_rate_limit_headers(limiter=limiter, client_ip=client_ip),
    )


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


@router.get("/v1/pricing/{tool}")
async def pricing_detail(request: Request) -> JSONResponse:
    """Return pricing info for a single tool."""
    tool_name = request.path_params["tool"]
    tool = get_tool(tool_name)
    if tool is None:
        return JSONResponse(
            {"success": False, "error": {"code": "tool_not_found", "message": f"Unknown tool: {tool_name}"}},
            status_code=404,
        )
    return JSONResponse({"tool": tool})


