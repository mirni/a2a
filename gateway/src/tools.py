"""Tool registry: maps tool names to async callables.

Each callable receives (ctx: AppContext, params: dict) and returns a result dict.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

from gateway.src.lifespan import AppContext

# Type alias for tool functions
ToolFunc = Callable[[AppContext, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


# ---------------------------------------------------------------------------
# Billing tools
# ---------------------------------------------------------------------------


async def _get_balance(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    balance = await ctx.tracker.get_balance(params["agent_id"])
    return {"balance": balance}


async def _get_usage_summary(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    summary = await ctx.tracker.get_usage_summary(
        params["agent_id"], since=params.get("since")
    )
    return summary


async def _deposit(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    new_balance = await ctx.tracker.wallet.deposit(
        params["agent_id"],
        params["amount"],
        description=params.get("description", ""),
    )
    return {"new_balance": new_balance}


# ---------------------------------------------------------------------------
# Payment tools
# ---------------------------------------------------------------------------


async def _create_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    intent = await ctx.payment_engine.create_intent(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        idempotency_key=params.get("idempotency_key"),
        metadata=params.get("metadata"),
    )
    return {"id": intent.id, "status": intent.status.value, "amount": intent.amount}


async def _capture_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    settlement = await ctx.payment_engine.capture(params["intent_id"])
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": settlement.amount,
    }


async def _create_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    escrow = await ctx.payment_engine.create_escrow(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        timeout_hours=params.get("timeout_hours"),
        metadata=params.get("metadata"),
    )
    return {"id": escrow.id, "status": escrow.status.value, "amount": escrow.amount}


async def _release_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    settlement = await ctx.payment_engine.release_escrow(params["escrow_id"])
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": settlement.amount,
    }


async def _get_payment_history(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    history = await ctx.payment_engine.get_payment_history(
        agent_id=params["agent_id"],
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"history": history}


# ---------------------------------------------------------------------------
# Marketplace tools
# ---------------------------------------------------------------------------


async def _search_services(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    # Import here to avoid bootstrap order issues
    from marketplace_src.models import ServiceSearchParams

    search_params = ServiceSearchParams(
        query=params.get("query"),
        category=params.get("category"),
        tags=params.get("tags"),
        max_cost=params.get("max_cost"),
        limit=params.get("limit", 20),
    )
    services = await ctx.marketplace.search(search_params)
    return {
        "services": [
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
    }


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
# Trust tools
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Paywall tools
# ---------------------------------------------------------------------------


async def _get_global_audit_log(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    entries = await ctx.paywall_storage.get_global_audit_log(
        since=params.get("since"),
        limit=params.get("limit", 100),
    )
    return {"entries": entries}


# ---------------------------------------------------------------------------
# Additional Trust tools
# ---------------------------------------------------------------------------


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
# Event Bus tools
# ---------------------------------------------------------------------------


async def _publish_event(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    event_id = await ctx.event_bus.publish(
        event_type=params["event_type"],
        source=params["source"],
        payload=params.get("payload", {}),
    )
    return {"event_id": event_id}


async def _get_events(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    events = await ctx.event_bus.get_events(
        event_type=params.get("event_type"),
        since_id=params.get("since_id", 0),
        limit=params.get("limit", 100),
    )
    return {"events": events}


# ---------------------------------------------------------------------------
# Webhook tools
# ---------------------------------------------------------------------------


async def _register_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.webhook_manager.register(
        agent_id=params["agent_id"],
        url=params["url"],
        event_types=params["event_types"],
        secret=params.get("secret", ""),
    )
    return result


async def _list_webhooks(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    webhooks = await ctx.webhook_manager.list_webhooks(params["agent_id"])
    return {"webhooks": webhooks}


async def _delete_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    deleted = await ctx.webhook_manager.delete_webhook(params["webhook_id"])
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Subscription Scheduler tools
# ---------------------------------------------------------------------------


async def _process_due_subscriptions(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    if ctx.scheduler is None:
        return {"error": "Scheduler not available"}
    result = await ctx.scheduler.process_due()
    return {
        "processed": result.processed,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "suspended": result.suspended,
        "expired_escrows": result.expired_escrows,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolFunc] = {
    # Billing
    "get_balance": _get_balance,
    "get_usage_summary": _get_usage_summary,
    "deposit": _deposit,
    # Payments
    "create_intent": _create_intent,
    "capture_intent": _capture_intent,
    "create_escrow": _create_escrow,
    "release_escrow": _release_escrow,
    "get_payment_history": _get_payment_history,
    # Marketplace
    "search_services": _search_services,
    "best_match": _best_match,
    "register_service": _register_service,
    # Trust
    "get_trust_score": _get_trust_score,
    "search_servers": _search_servers,
    "delete_server": _delete_server,
    "update_server": _update_server,
    # Paywall
    "get_global_audit_log": _get_global_audit_log,
    # Event Bus
    "publish_event": _publish_event,
    "get_events": _get_events,
    # Webhooks
    "register_webhook": _register_webhook,
    "list_webhooks": _list_webhooks,
    "delete_webhook": _delete_webhook,
    # Scheduler
    "process_due_subscriptions": _process_due_subscriptions,
}
