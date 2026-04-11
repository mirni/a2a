"""Health check endpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.src._version import __version__
from gateway.src.catalog import tool_count
from gateway.src.rate_limit_headers import public_rate_limit_headers

logger = logging.getLogger("a2a.health")

router = APIRouter()


def _get_db_connections(ctx: Any) -> dict[str, Any]:
    """Extract all database connections from the application context.

    Returns a mapping of database name to its connection object.
    Each connection is expected to support ``await conn.execute("SELECT 1")``.
    """
    connections: dict[str, Any] = {}

    # billing — ctx.tracker.storage.db
    connections["billing"] = ctx.tracker.storage.db

    # paywall — ctx.paywall_storage.db
    connections["paywall"] = ctx.paywall_storage.db

    # payments — ctx.payment_engine.storage.db
    connections["payments"] = ctx.payment_engine.storage.db

    # marketplace — ctx.marketplace._storage.db
    connections["marketplace"] = ctx.marketplace._storage.db

    # trust — ctx.trust_api.storage.db
    connections["trust"] = ctx.trust_api.storage.db

    # identity — ctx.identity_api.storage.db
    connections["identity"] = ctx.identity_api.storage.db

    # event_bus — ctx.event_bus.db
    connections["event_bus"] = ctx.event_bus.db

    # webhooks — ctx.webhook_manager._require_db()
    connections["webhooks"] = ctx.webhook_manager._require_db()

    # messaging — ctx.messaging_api._storage._require_db()
    connections["messaging"] = ctx.messaging_api._storage._require_db()

    # disputes — ctx.dispute_engine.db (direct attribute)
    connections["disputes"] = ctx.dispute_engine.db

    return connections


async def _probe_db(name: str, conn: Any) -> str:
    """Probe a single database with ``SELECT 1`` and return its status."""
    try:
        await conn.execute("SELECT 1")
        return "ok"
    except Exception:
        logger.warning("Health check DB probe failed for '%s'", name, exc_info=True)
        return "error"


@router.get("/v1/health")
async def health(request: Request) -> JSONResponse:
    status = "ok"
    http_status = 200

    ctx = request.app.state.ctx

    # Probe all product databases
    databases: dict[str, str] = {}
    try:
        connections = _get_db_connections(ctx)
    except Exception:
        logger.warning("Failed to retrieve DB connections", exc_info=True)
        connections = {}

    # v1.2.4 audit P0-7: probe all DBs concurrently rather than
    # serialising 10 round-trips. Each `SELECT 1` is cheap but on a
    # slow-I/O deploy (sandbox) the serial version was a major
    # contributor to the 5.2s p50 the audit measured.
    if connections:
        names = list(connections.keys())
        results = await asyncio.gather(
            *(_probe_db(name, connections[name]) for name in names),
            return_exceptions=False,
        )
        databases = dict(zip(names, results, strict=True))

    # If any database reports an error, the overall status is degraded
    has_errors = any(s == "error" for s in databases.values())
    if has_errors:
        status = "degraded"
        http_status = 503

    # Legacy 'db' field: reflects billing DB status for backward compatibility
    billing_status = databases.get("billing", "error")

    # Use actual IP-based remaining count when the public rate limiter is active
    limiter = getattr(request.state, "public_rate_limiter", None)
    client_ip = getattr(request.state, "client_ip", None)

    return JSONResponse(
        {
            "status": status,
            "version": __version__,
            "tools": tool_count(),
            "db": billing_status,
            "databases": databases,
        },
        status_code=http_status,
        headers=public_rate_limit_headers(limiter=limiter, client_ip=client_ip),
    )
