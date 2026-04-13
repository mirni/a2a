"""Marketplace, strategy, service rating, and Atlas tool functions."""

from __future__ import annotations

import time as _time
from typing import Any

import httpx

from gateway.src.lifespan import AppContext
from gateway.src.tools._pagination import _paginate


async def _search_services(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from marketplace_src.models import ServiceSearchParams

    paginate = params.get("paginate", False)
    offset = max(0, int(params.get("offset", 0)))
    limit = int(params.get("limit", 20))

    search_params = ServiceSearchParams(
        query=params.get("query"),
        category=params.get("category"),
        tags=params.get("tags"),
        max_cost=params.get("max_cost"),
        limit=limit,
        offset=offset,
    )
    services = await ctx.marketplace.search(search_params)

    service_dicts = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "pricing": s.pricing.to_dict(),
            "tags": s.tags,
            "endpoint": s.endpoint,
            "trust_score": s.trust_score,
        }
        for s in services
    ]

    if paginate:
        total = await ctx.marketplace.storage.count_search_results(
            query=params.get("query"),
            category=params.get("category"),
            tags=params.get("tags"),
            max_cost=params.get("max_cost"),
        )
        return _paginate(service_dicts, params, total_override=total)

    return {"services": service_dicts}


async def _best_match(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from marketplace_src.models import MatchPreference

    prefer = MatchPreference(params.get("prefer", "trust"))
    matches = await ctx.marketplace.best_match(
        query=params["query"],
        budget=params.get("budget"),
        min_trust_score=params.get("min_trust_score"),
        prefer=prefer,
        limit=params.get("limit", 5),
    )
    return {
        "matches": [
            {
                "service": {
                    "id": m.service.id,
                    "name": m.service.name,
                    "description": m.service.description,
                    "pricing": m.service.pricing.to_dict(),
                    "trust_score": m.service.trust_score,
                },
                "rank_score": m.rank_score,
                "match_reasons": m.match_reasons,
            }
            for m in matches
        ]
    }


async def _get_service(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    service = await ctx.marketplace.get_service(params["service_id"])
    return {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "category": service.category,
        "pricing": service.pricing.to_dict(),
        "tags": service.tags,
        "endpoint": service.endpoint,
        "trust_score": service.trust_score,
        "status": service.status.value,
    }


async def _update_service(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    service = await ctx.marketplace.update_service(
        params["service_id"],
        name=params.get("name"),
        description=params.get("description"),
        category=params.get("category"),
        tags=params.get("tags"),
        endpoint=params.get("endpoint"),
        metadata=params.get("metadata"),
    )
    return {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "category": service.category,
        "pricing": service.pricing.to_dict(),
        "tags": service.tags,
        "endpoint": service.endpoint,
        "status": service.status.value,
    }


async def _deactivate_service(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    service = await ctx.marketplace.deactivate_service(params["service_id"])
    return {
        "id": service.id,
        "name": service.name,
        "status": service.status.value,
    }


async def _register_service(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    pricing_data = params.get("pricing")
    pricing = (
        PricingModel(
            model=PricingModelType(pricing_data.get("model", "free")),
            cost=pricing_data.get("cost", 0.0),
        )
        if pricing_data
        else PricingModel(model=PricingModelType.FREE)
    )

    spec = ServiceCreate(
        provider_id=params["provider_id"],
        name=params["name"],
        description=params["description"],
        category=params["category"],
        tools=params.get("tools", []),
        tags=params.get("tags", []),
        endpoint=params.get("endpoint", ""),
        pricing=pricing,
    )
    service = await ctx.marketplace.register_service(spec)
    return {"id": service.id, "name": service.name, "status": service.status.value}


# ---------------------------------------------------------------------------
# Strategy marketplace
# ---------------------------------------------------------------------------


async def _list_strategies(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """List marketplace services in the 'strategy' category."""
    from marketplace_src.models import ServiceSearchParams

    search_params = ServiceSearchParams(
        category="strategy",
        tags=params.get("tags"),
        max_cost=params.get("max_cost"),
        limit=params.get("limit", 50),
    )
    services = await ctx.marketplace.search(search_params)
    return {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "pricing": s.pricing.to_dict(),
                "tags": s.tags,
                "trust_score": s.trust_score,
                "provider_id": s.provider_id,
            }
            for s in services
        ]
    }


# ---------------------------------------------------------------------------
# Service Ratings (P3-20)
# ---------------------------------------------------------------------------


async def _rate_service_tool(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Rate a marketplace service (1-5). Upserts per agent per service."""
    service_id = params["service_id"]
    agent_id = params["agent_id"]
    rating = int(params["rating"])
    review = params.get("review", "")

    if rating < 1 or rating > 5:
        from gateway.src.tool_errors import ToolValidationError

        raise ToolValidationError("Rating must be between 1 and 5")

    import time as _time

    now = _time.time()

    db = ctx.marketplace.storage.db
    await db.execute(
        """INSERT INTO service_ratings (service_id, agent_id, rating, review, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(service_id, agent_id) DO UPDATE SET
             rating = excluded.rating,
             review = excluded.review,
             created_at = excluded.created_at""",
        (service_id, agent_id, rating, review, now),
    )
    await db.commit()

    return {
        "service_id": service_id,
        "agent_id": agent_id,
        "rating": rating,
        "review": review,
    }


async def _get_service_ratings_tool(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get ratings and reviews for a marketplace service."""
    service_id = params["service_id"]
    limit = params.get("limit", 20)

    db = ctx.marketplace.storage.db
    await db.execute(
        """CREATE TABLE IF NOT EXISTS service_ratings (
            service_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (service_id, agent_id)
        )"""
    )

    cursor = await db.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as cnt FROM service_ratings WHERE service_id = ?",
        (service_id,),
    )
    row = await cursor.fetchone()
    avg_rating = round(row["avg_rating"], 2) if row["avg_rating"] is not None else 0
    count = row["cnt"] if row else 0

    cursor2 = await db.execute(
        "SELECT agent_id, rating, review, created_at FROM service_ratings "
        "WHERE service_id = ? ORDER BY created_at DESC LIMIT ?",
        (service_id, limit),
    )
    rows = await cursor2.fetchall()
    ratings = [
        {
            "agent_id": r["agent_id"],
            "rating": r["rating"],
            "review": r["review"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    return {
        "average_rating": avg_rating,
        "count": count,
        "ratings": ratings,
    }


# ---------------------------------------------------------------------------
# Agent Search/Discovery (by capabilities)
# ---------------------------------------------------------------------------


async def _search_agents(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Search for agents by capability keywords.

    Searches across service names, descriptions, tools, tags, and categories.
    Groups results by provider (agent).
    """
    query = params["query"].lower()
    limit = int(params.get("limit", 20))

    db = ctx.marketplace.storage.db

    # Search across services for the query term
    cursor = await db.execute(
        """
        SELECT DISTINCT s.provider_id, s.id, s.name, s.description, s.category
        FROM services s
        LEFT JOIN service_tools st ON s.id = st.service_id
        LEFT JOIN service_tags stg ON s.id = stg.service_id
        WHERE s.status = 'active'
          AND (
            LOWER(s.name) LIKE ?
            OR LOWER(s.description) LIKE ?
            OR LOWER(s.category) LIKE ?
            OR LOWER(st.tool_name) LIKE ?
            OR LOWER(stg.tag) LIKE ?
          )
        ORDER BY s.provider_id, s.name
        """,
        tuple(f"%{query}%" for _ in range(5)),
    )
    rows = await cursor.fetchall()

    # Group by provider_id (agent)
    agents_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row["provider_id"]
        if pid not in agents_map:
            agents_map[pid] = {"agent_id": pid, "services": []}
        agents_map[pid]["services"].append(
            {
                "service_id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
            }
        )

    all_agents = list(agents_map.values())

    if params.get("paginate"):
        return _paginate(all_agents, params)

    return {"agents": all_agents[:limit]}


# ---------------------------------------------------------------------------
# Atlas Discovery & Brokering (Project Atlas MVP)
# ---------------------------------------------------------------------------


async def _atlas_discover(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Enriched discovery: marketplace + trust + reputation + ratings → Atlas Score."""
    from marketplace_src.atlas import compute_atlas_score
    from marketplace_src.models import MatchPreference

    prefer = MatchPreference(params.get("prefer", "trust"))
    limit = int(params.get("limit", 5))
    capabilities = params.get("capabilities")

    matches = await ctx.marketplace.best_match(
        query=params["query"],
        budget=params.get("budget"),
        min_trust_score=params.get("min_trust_score"),
        prefer=prefer,
        limit=limit * 3,
    )

    results = []
    for m in matches:
        service = m.service

        # Filter by capabilities (required tool names)
        if capabilities:
            svc_tools = set(service.tools) if hasattr(service, "tools") and service.tools else set()
            if not set(capabilities).issubset(svc_tools):
                continue

        # Enrich: trust breakdown
        trust_composite: float | None = None
        try:
            score = await ctx.trust_api.get_score(server_id=service.provider_id)
            trust_composite = score.composite_score
        except Exception:
            pass

        # Enrich: identity reputation
        reputation_data: dict[str, Any] = {}
        reputation_composite: float | None = None
        transaction_volume_score: float | None = None
        try:
            rep = await ctx.identity_api.get_reputation(service.provider_id)
            if rep is not None:
                reputation_data = {
                    "payment_reliability": rep.payment_reliability,
                    "data_source_quality": rep.data_source_quality,
                    "transaction_volume_score": rep.transaction_volume_score,
                    "composite_score": rep.composite_score,
                }
                reputation_composite = rep.composite_score
                transaction_volume_score = rep.transaction_volume_score
        except Exception:
            pass

        # Enrich: service ratings
        avg_rating = 0.0
        try:
            ratings_result = await _get_service_ratings_tool(ctx, {"service_id": service.id, "limit": 0})
            avg_rating = ratings_result.get("average_rating", 0.0)
        except Exception:
            pass

        atlas = compute_atlas_score(
            trust_composite=trust_composite,
            reputation_composite=reputation_composite,
            average_rating=avg_rating,
            transaction_volume_score=transaction_volume_score,
        )

        results.append(
            {
                "service": {
                    "id": service.id,
                    "name": service.name,
                    "description": service.description,
                    "provider_id": service.provider_id,
                    "pricing": service.pricing.to_dict(),
                    "endpoint": service.endpoint,
                },
                "atlas_score": atlas.total,
                "atlas_breakdown": {
                    "trust_component": atlas.trust_component,
                    "reputation_component": atlas.reputation_component,
                    "marketplace_component": atlas.marketplace_component,
                    "volume_component": atlas.volume_component,
                },
                "trust_score": trust_composite,
                "reputation": reputation_data or None,
                "average_rating": avg_rating,
                "rank_score": m.rank_score,
            }
        )

    # Sort by atlas_score DESC
    results.sort(key=lambda r: r["atlas_score"], reverse=True)
    return {"results": results[:limit]}


async def _atlas_preflight(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Pre-transaction verification for a marketplace service."""
    from gateway.src.tool_errors import ToolNotFoundError

    service_id = params["service_id"]
    min_trust = params.get("min_trust_score")
    expected_cost = params.get("expected_cost")

    start = _time.monotonic()

    # Fetch service (raises ToolNotFoundError if missing)
    try:
        service = await ctx.marketplace.get_service(service_id)
    except Exception as exc:
        raise ToolNotFoundError(f"Service not found: {service_id}") from exc

    checks: dict[str, str] = {}

    # Check endpoint reachability
    endpoint = service.endpoint if hasattr(service, "endpoint") else ""
    if endpoint:
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.head(endpoint, timeout=5.0)
            checks["endpoint"] = "ok" if resp.status_code < 500 else "fail"
        except Exception:
            checks["endpoint"] = "fail"
    else:
        checks["endpoint"] = "fail"

    # Check trust
    if min_trust is not None:
        try:
            score = await ctx.trust_api.get_score(server_id=service.provider_id)
            checks["trust"] = "ok" if score.composite_score >= min_trust else "fail"
        except Exception:
            checks["trust"] = "fail"
    else:
        checks["trust"] = "ok"

    # Check wallet
    try:
        await ctx.tracker.wallet.get_balance(service.provider_id)
        checks["wallet"] = "ok"
    except Exception:
        checks["wallet"] = "ok"  # No wallet doesn't mean failure for the provider

    # Check pricing
    if expected_cost is not None:
        from decimal import Decimal

        svc_cost = Decimal(str(service.pricing.cost)) if hasattr(service.pricing, "cost") else Decimal("0")
        checks["pricing"] = "ok" if svc_cost == Decimal(str(expected_cost)) else "fail"
    else:
        checks["pricing"] = "ok"

    elapsed_ms = round((_time.monotonic() - start) * 1000, 1)
    ready = all(v == "ok" for v in checks.values())

    return {
        "ready": ready,
        "checks": checks,
        "service_id": service_id,
        "latency_ms": elapsed_ms,
    }


async def _atlas_broker(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """One-call brokering: discover → preflight → create payment intent."""
    from gateway.src.tools.payments import _create_intent

    query = params["query"]
    payer = params["payer"]
    description = params.get("description", "")

    # Step 1: Discover candidates
    discover_result = await _atlas_discover(
        ctx,
        {
            "query": query,
            "budget": params.get("budget"),
            "min_trust_score": params.get("min_trust_score"),
            "prefer": params.get("prefer", "trust"),
            "limit": 5,
        },
    )

    candidates = discover_result.get("results", [])
    if not candidates:
        return {"match": None, "error": "No candidate passed preflight"}

    # Step 2: Preflight each candidate until one passes
    for candidate in candidates:
        svc = candidate["service"]
        preflight = await _atlas_preflight(
            ctx,
            {
                "service_id": svc["id"],
                "min_trust_score": params.get("min_trust_score"),
            },
        )
        if preflight["ready"]:
            # Step 3: Create payment intent
            pricing = svc.get("pricing", {})
            amount = pricing.get("cost", 0)
            try:
                intent = await _create_intent(
                    ctx,
                    {
                        "payer": payer,
                        "payee": svc["provider_id"],
                        "amount": amount if amount > 0 else 1.0,
                        "description": description or f"Atlas brokered: {svc['name']}",
                    },
                )
                return {
                    "match": svc,
                    "intent_id": intent.get("id"),
                    "intent_status": intent.get("status"),
                    "atlas_score": candidate["atlas_score"],
                    "preflight": preflight,
                }
            except Exception as exc:
                return {
                    "match": svc,
                    "intent_id": None,
                    "intent_status": "failed",
                    "atlas_score": candidate["atlas_score"],
                    "preflight": preflight,
                    "error": str(exc),
                }

    return {"match": None, "error": "No candidate passed preflight"}
