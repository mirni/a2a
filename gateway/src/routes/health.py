"""Health check endpoint."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.src.catalog import tool_count


async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "version": "0.1.0",
        "tools": tool_count(),
    })


routes = [Route("/health", health, methods=["GET"])]
