"""Health check endpoint."""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.src.catalog import tool_count
from gateway.src.rate_limit_headers import public_rate_limit_headers

logger = logging.getLogger("a2a.health")


async def health(request: Request) -> JSONResponse:
    db_status = "ok"
    status = "ok"
    http_status = 200

    # Deep health check: probe the billing DB with SELECT 1
    try:
        ctx = request.app.state.ctx
        await ctx.tracker.storage.db.execute("SELECT 1")
        db_status = "ok"
    except Exception:
        logger.warning("Health check DB probe failed", exc_info=True)
        db_status = "error"
        status = "degraded"
        http_status = 503

    return JSONResponse(
        {
            "status": status,
            "version": "0.1.0",
            "tools": tool_count(),
            "db": db_status,
        },
        status_code=http_status,
        headers=public_rate_limit_headers(),
    )


routes = [Route("/v1/health", health, methods=["GET"])]
