"""Pricing / catalog endpoints."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.src.catalog import get_catalog, get_tool


async def pricing_list(request: Request) -> JSONResponse:
    """Return the full tool catalog."""
    return JSONResponse({"tools": get_catalog()})


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


routes = [
    Route("/pricing", pricing_list, methods=["GET"]),
    Route("/pricing/{tool}", pricing_detail, methods=["GET"]),
]
