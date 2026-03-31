"""Trust score, server management, and SLA tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext


def _resolve_server_id(params: dict[str, Any]) -> str:
    """Resolve ``server_id`` from params, accepting ``agent_id`` as alias.

    The rest of the platform uses ``agent_id`` while trust tools historically
    use ``server_id``.  This helper accepts both, preferring ``server_id``
    when both are supplied (backward-compatible).
    """
    server_id = params.get("server_id")
    if server_id is None:
        server_id = params.get("agent_id")
    if server_id is None:
        raise KeyError("server_id")
    return server_id


async def _register_server(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Register a new server for trust tracking."""
    server = await ctx.trust_api.register_server(
        name=params["name"],
        url=params["url"],
        transport_type=params.get("transport_type", "http"),
        server_id=params.get("server_id"),
    )
    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "transport_type": server.transport_type.value,
    }


async def _get_trust_score(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from trust_src.models import Window

    server_id = _resolve_server_id(params)
    window = Window(params.get("window", "24h"))
    score = await ctx.trust_api.get_score(
        server_id=server_id,
        window=window,
        recompute=params.get("recompute", False),
    )
    return {
        "server_id": score.server_id,
        "composite_score": score.composite_score,
        "reliability_score": score.reliability_score,
        "security_score": score.security_score,
        "documentation_score": score.documentation_score,
        "responsiveness_score": score.responsiveness_score,
        "confidence": score.confidence,
        "window": score.window.value,
    }


async def _search_servers(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    servers = await ctx.trust_api.search_servers(
        name_contains=params.get("name_contains"),
        min_score=params.get("min_score"),
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {
        "servers": [
            {
                "id": s.id,
                "name": s.name,
                "url": s.url,
                "transport_type": s.transport_type.value,
            }
            for s in servers
        ]
    }


async def _delete_server(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    server_id = _resolve_server_id(params)
    await ctx.trust_api.delete_server(server_id)
    return {"deleted": True}


async def _update_server(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    server_id = _resolve_server_id(params)
    server = await ctx.trust_api.update_server(
        server_id,
        name=params.get("name"),
        url=params.get("url"),
    )
    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "transport_type": server.transport_type.value,
    }


# ---------------------------------------------------------------------------
# SLA Enforcement
# ---------------------------------------------------------------------------


async def _check_sla_compliance(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Check if a server meets its claimed SLA based on trust probe data."""
    server_id = _resolve_server_id(params)
    return await ctx.trust_api.check_sla_compliance(
        server_id=server_id,
        claimed_uptime=float(params.get("claimed_uptime", 99.0)),
    )
