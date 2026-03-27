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
# Subscription tools
# ---------------------------------------------------------------------------


async def _create_subscription(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    sub = await ctx.payment_engine.create_subscription(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        interval=params["interval"],
        description=params.get("description", ""),
        metadata=params.get("metadata"),
    )
    return {
        "id": sub.id,
        "status": sub.status.value,
        "amount": sub.amount,
        "interval": sub.interval.value,
        "next_charge_at": sub.next_charge_at,
    }


async def _cancel_subscription(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    sub = await ctx.payment_engine.cancel_subscription(
        sub_id=params["subscription_id"],
        cancelled_by=params.get("cancelled_by"),
    )
    return {"id": sub.id, "status": sub.status.value}


async def _get_subscription(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    sub = await ctx.payment_engine.get_subscription(params["subscription_id"])
    return {
        "id": sub.id,
        "payer": sub.payer,
        "payee": sub.payee,
        "amount": sub.amount,
        "interval": sub.interval.value,
        "status": sub.status.value,
        "next_charge_at": sub.next_charge_at,
        "charge_count": sub.charge_count,
        "created_at": sub.created_at,
    }


async def _list_subscriptions(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    subs = await ctx.payment_engine.storage.list_subscriptions(
        agent_id=params.get("agent_id"),
        status=params.get("status"),
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"subscriptions": subs}


async def _reactivate_subscription(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    sub = await ctx.payment_engine.reactivate_subscription(params["subscription_id"])
    return {"id": sub.id, "status": sub.status.value}


# ---------------------------------------------------------------------------
# Wallet tools
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Performance-gated escrow tools
# ---------------------------------------------------------------------------


async def _create_performance_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create escrow that auto-releases when payee's verified metric meets threshold."""
    escrow = await ctx.payment_engine.create_escrow(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        metadata={
            "performance_gated": True,
            "metric_name": params["metric_name"],
            "threshold": params["threshold"],
        },
    )
    return {
        "escrow_id": escrow.id,
        "status": escrow.status.value,
        "amount": escrow.amount,
        "metric_name": params["metric_name"],
        "threshold": params["threshold"],
    }


async def _check_performance_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Check if payee's verified metrics meet the escrow threshold; auto-release if so."""
    escrow = await ctx.payment_engine.get_escrow(params["escrow_id"])
    meta = escrow.metadata or {}

    if not meta.get("performance_gated"):
        return {"error": "Not a performance-gated escrow", "released": False}

    if escrow.status.value != "held":
        return {"released": escrow.status.value == "settled", "status": escrow.status.value}

    metric_name = meta["metric_name"]
    threshold = float(meta["threshold"])

    # Check payee's verified claims
    claims = await ctx.identity_api.get_verified_claims(escrow.payee)
    for claim in claims:
        if claim.metric_name == metric_name:
            # For "gte" claims (higher is better): bound_value >= threshold
            if claim.claim_type == "gte" and claim.bound_value >= threshold:
                settlement = await ctx.payment_engine.release_escrow(escrow.id)
                return {"released": True, "settlement_id": settlement.id}
            # For "lte" claims (lower is better): bound_value <= threshold
            if claim.claim_type == "lte" and claim.bound_value <= threshold:
                settlement = await ctx.payment_engine.release_escrow(escrow.id)
                return {"released": True, "settlement_id": settlement.id}

    return {"released": False, "reason": "Metric threshold not met"}


# ---------------------------------------------------------------------------
# Dispute tools
# ---------------------------------------------------------------------------


async def _open_dispute(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.dispute_engine.open_dispute(
        escrow_id=params["escrow_id"],
        opener=params["opener"],
        reason=params.get("reason", ""),
    )


async def _respond_to_dispute(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.dispute_engine.respond_to_dispute(
        dispute_id=params["dispute_id"],
        respondent=params["respondent"],
        response=params["response"],
    )


async def _resolve_dispute(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.dispute_engine.resolve_dispute(
        dispute_id=params["dispute_id"],
        resolution=params["resolution"],
        resolved_by=params["resolved_by"],
        notes=params.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Key rotation tools
# ---------------------------------------------------------------------------


async def _rotate_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Revoke current key and create a new one with the same tier."""
    current_key = params["current_key"]
    # Validate and get current key info
    key_info = await ctx.key_manager.validate_key(current_key)
    agent_id = key_info["agent_id"]
    tier = key_info["tier"]

    # Revoke old key
    revoked = await ctx.key_manager.revoke_key(current_key)

    # Create new key with same tier
    new_key_info = await ctx.key_manager.create_key(agent_id, tier=tier)

    return {
        "new_key": new_key_info["key"],
        "tier": tier,
        "agent_id": agent_id,
        "revoked": revoked,
    }


async def _create_wallet(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    wallet = await ctx.tracker.wallet.create(
        params["agent_id"],
        initial_balance=params.get("initial_balance", 0.0),
    )
    return wallet


async def _withdraw(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    new_balance = await ctx.tracker.wallet.withdraw(
        params["agent_id"],
        params["amount"],
        description=params.get("description", ""),
    )
    return {"new_balance": new_balance}


# ---------------------------------------------------------------------------
# Identity tools
# ---------------------------------------------------------------------------


async def _register_agent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    identity = await ctx.identity_api.register_agent(
        agent_id=params["agent_id"],
        public_key=params.get("public_key"),
    )
    return {
        "agent_id": identity.agent_id,
        "public_key": identity.public_key,
        "created_at": identity.created_at,
    }


async def _verify_agent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    message = params["message"].encode() if isinstance(params["message"], str) else params["message"]
    valid = await ctx.identity_api.verify_agent(
        agent_id=params["agent_id"],
        message=message,
        signature_hex=params["signature"],
    )
    return {"valid": valid}


async def _submit_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    attestation = await ctx.identity_api.submit_metrics(
        agent_id=params["agent_id"],
        metrics=params["metrics"],
        data_source=params.get("data_source", "self_reported"),
    )
    return {
        "agent_id": attestation.agent_id,
        "commitment_hashes": attestation.commitment_hashes,
        "verified_at": attestation.verified_at,
        "valid_until": attestation.valid_until,
        "data_source": attestation.data_source,
        "signature": attestation.signature,
    }


async def _get_agent_identity(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    identity = await ctx.identity_api.get_identity(params["agent_id"])
    if identity is None:
        return {"agent_id": params["agent_id"], "found": False}
    return {
        "agent_id": identity.agent_id,
        "public_key": identity.public_key,
        "created_at": identity.created_at,
        "org_id": identity.org_id,
        "found": True,
    }


async def _get_verified_claims(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    claims = await ctx.identity_api.get_verified_claims(params["agent_id"])
    return {
        "claims": [
            {
                "agent_id": c.agent_id,
                "metric_name": c.metric_name,
                "claim_type": c.claim_type,
                "bound_value": c.bound_value,
                "valid_until": c.valid_until,
            }
            for c in claims
        ]
    }


async def _search_agents_by_metrics(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    agents = await ctx.identity_api.search_agents_by_metrics(
        metric_name=params["metric_name"],
        min_value=params.get("min_value"),
        max_value=params.get("max_value"),
        limit=params.get("limit", 50),
    )
    return {"agents": agents}


async def _get_agent_reputation(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    reputation = await ctx.identity_api.get_reputation(params["agent_id"])
    if reputation is None:
        return {"agent_id": params["agent_id"], "found": False}
    return {
        "agent_id": reputation.agent_id,
        "payment_reliability": reputation.payment_reliability,
        "data_source_quality": reputation.data_source_quality,
        "transaction_volume_score": reputation.transaction_volume_score,
        "composite_score": reputation.composite_score,
        "confidence": reputation.confidence,
        "found": True,
    }


# ---------------------------------------------------------------------------
# Historical claim chain tools
# ---------------------------------------------------------------------------


async def _build_claim_chain(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.identity_api.build_claim_chain(params["agent_id"])


async def _get_claim_chains(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    chains = await ctx.identity_api.storage.get_claim_chains(
        params["agent_id"], limit=params.get("limit", 10)
    )
    return {"chains": chains}


# ---------------------------------------------------------------------------
# Messaging tools
# ---------------------------------------------------------------------------


async def _send_message(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    msg = await ctx.messaging_api.send_message(
        sender=params["sender"],
        recipient=params["recipient"],
        message_type=params["message_type"],
        subject=params.get("subject", ""),
        body=params.get("body", ""),
        metadata=params.get("metadata"),
        thread_id=params.get("thread_id"),
    )
    return {
        "id": msg.id,
        "sender": msg.sender,
        "recipient": msg.recipient,
        "message_type": msg.message_type.value,
        "thread_id": msg.thread_id,
        "created_at": msg.created_at,
    }


async def _get_messages(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    messages = await ctx.messaging_api.get_messages(
        agent_id=params["agent_id"],
        thread_id=params.get("thread_id"),
        limit=params.get("limit", 50),
    )
    return {"messages": messages}


async def _negotiate_price(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.messaging_api.negotiate_price(
        initiator=params["initiator"],
        responder=params["responder"],
        amount=params["amount"],
        service_id=params.get("service_id", ""),
        expires_hours=params.get("expires_hours", 24),
    )
    return result


# ---------------------------------------------------------------------------
# SLA enforcement tools
# ---------------------------------------------------------------------------


async def _check_sla_compliance(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Check if a server meets its claimed SLA based on trust probe data."""
    server_id = params["server_id"]
    claimed_uptime = float(params.get("claimed_uptime", 99.0))

    from trust_src.models import Window
    score = await ctx.trust_api.get_score(server_id=server_id, window=Window("24h"))

    # reliability_score is 0-100, maps to uptime percentage
    actual_uptime = score.reliability_score
    compliant = actual_uptime >= claimed_uptime
    violation_pct = max(0.0, claimed_uptime - actual_uptime) if not compliant else 0.0

    return {
        "server_id": server_id,
        "claimed_uptime": claimed_uptime,
        "actual_uptime": round(actual_uptime, 2),
        "compliant": compliant,
        "violation_pct": round(violation_pct, 2),
        "confidence": score.confidence,
    }


# ---------------------------------------------------------------------------
# Strategy marketplace tools
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
# Analytics tools
# ---------------------------------------------------------------------------


async def _get_service_analytics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get usage analytics for an agent."""
    summary = await ctx.tracker.get_usage_summary(
        params["agent_id"], since=params.get("since")
    )
    return {
        "agent_id": params["agent_id"],
        "total_calls": summary.get("total_calls", 0),
        "total_cost": summary.get("total_cost", 0.0),
        "total_tokens": summary.get("total_tokens", 0),
    }


async def _get_revenue_report(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get revenue report for a provider — aggregates incoming payments."""
    agent_id = params["agent_id"]
    history = await ctx.payment_engine.get_payment_history(agent_id, limit=1000)
    # Filter settlements where agent is payee
    incoming = [h for h in history if h.get("payee") == agent_id and h.get("type") == "settlement"]
    total_revenue = sum(h.get("amount", 0) for h in incoming)
    return {
        "agent_id": agent_id,
        "total_revenue": total_revenue,
        "payment_count": len(incoming),
        "history": incoming[:params.get("limit", 50)],
    }


# ---------------------------------------------------------------------------
# Multi-party payment split tools
# ---------------------------------------------------------------------------


async def _create_split_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a payment split across multiple payees.

    Splits must sum to 100%. Withdraws full amount from payer, deposits to each payee.
    """
    payer = params["payer"]
    amount = float(params["amount"])
    splits = params["splits"]
    description = params.get("description", "")

    # Validate percentages sum to 100
    total_pct = sum(s["percentage"] for s in splits)
    if abs(total_pct - 100) > 0.01:
        raise ValueError(f"Split percentages must sum to 100, got {total_pct}")

    # Withdraw full amount from payer
    await ctx.tracker.wallet.withdraw(payer, amount, description=f"split:{description}")

    # Deposit to each payee
    settlements = []
    for split in splits:
        payee = split["payee"]
        share = round(amount * split["percentage"] / 100.0, 2)
        await ctx.tracker.wallet.deposit(payee, share, description=f"split_from:{payer}")
        settlements.append({"payee": payee, "amount": share, "percentage": split["percentage"]})

    return {
        "status": "settled",
        "payer": payer,
        "total_amount": amount,
        "settlements": settlements,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolFunc] = {
    # Billing
    "get_balance": _get_balance,
    "get_usage_summary": _get_usage_summary,
    "deposit": _deposit,
    "create_wallet": _create_wallet,
    "withdraw": _withdraw,
    # Payments
    "create_intent": _create_intent,
    "capture_intent": _capture_intent,
    "create_escrow": _create_escrow,
    "release_escrow": _release_escrow,
    "get_payment_history": _get_payment_history,
    # Subscriptions
    "create_subscription": _create_subscription,
    "cancel_subscription": _cancel_subscription,
    "get_subscription": _get_subscription,
    "list_subscriptions": _list_subscriptions,
    "reactivate_subscription": _reactivate_subscription,
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
    # Identity
    "register_agent": _register_agent,
    "verify_agent": _verify_agent,
    "submit_metrics": _submit_metrics,
    "get_agent_identity": _get_agent_identity,
    "get_verified_claims": _get_verified_claims,
    "get_agent_reputation": _get_agent_reputation,
    "search_agents_by_metrics": _search_agents_by_metrics,
    # Performance-gated escrow
    "create_performance_escrow": _create_performance_escrow,
    "check_performance_escrow": _check_performance_escrow,
    # Disputes
    "open_dispute": _open_dispute,
    "respond_to_dispute": _respond_to_dispute,
    "resolve_dispute": _resolve_dispute,
    # Key rotation
    "rotate_key": _rotate_key,
    # Historical claims
    "build_claim_chain": _build_claim_chain,
    "get_claim_chains": _get_claim_chains,
    # Messaging
    "send_message": _send_message,
    "get_messages": _get_messages,
    "negotiate_price": _negotiate_price,
    # SLA enforcement
    "check_sla_compliance": _check_sla_compliance,
    # Strategy marketplace
    "list_strategies": _list_strategies,
    # Analytics
    "get_service_analytics": _get_service_analytics,
    "get_revenue_report": _get_revenue_report,
    # Multi-party splits
    "create_split_intent": _create_split_intent,
}
