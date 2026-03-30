"""Trust score, server management, and SLA tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext


async def _get_trust_score(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from trust_src.models import Window

    window = Window(params.get("window", "24h"))
    score = await ctx.trust_api.get_score(
        server_id=params["server_id"],
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
    await ctx.trust_api.delete_server(params["server_id"])
    return {"deleted": True}


async def _update_server(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    server = await ctx.trust_api.update_server(
        params["server_id"],
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
    return await ctx.trust_api.check_sla_compliance(
        server_id=params["server_id"],
        claimed_uptime=float(params.get("claimed_uptime", 99.0)),
    )
