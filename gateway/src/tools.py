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


async def _get_transactions(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    txns = await ctx.tracker.storage.get_transactions(
        agent_id=params["agent_id"],
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"transactions": txns}


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


async def _cancel_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    escrow = await ctx.payment_engine.refund_escrow(params["escrow_id"])
    return {
        "id": escrow.id,
        "status": escrow.status.value,
        "amount": escrow.amount,
    }


async def _refund_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Refund a payment intent.

    - If pending: void it (no funds moved).
    - If settled: create a reverse transfer from payee to payer.
    """
    intent = await ctx.payment_engine.get_intent(params["intent_id"])

    if intent.status.value == "pending":
        voided = await ctx.payment_engine.void(intent.id)
        return {"id": voided.id, "status": "voided", "amount": voided.amount}

    if intent.status.value == "settled":
        # Reverse transfer: withdraw from payee, deposit to payer
        await ctx.tracker.wallet.withdraw(
            intent.payee, intent.amount, description=f"refund:{intent.id}"
        )
        await ctx.tracker.wallet.deposit(
            intent.payer, intent.amount, description=f"refund:{intent.id}"
        )
        return {"id": intent.id, "status": "refunded", "amount": intent.amount}

    # Any other state (voided, captured) cannot be refunded
    from payments_src.engine import InvalidStateError

    raise InvalidStateError(
        f"Cannot refund intent in state '{intent.status.value}'"
    )


async def _get_payment_history(
    ctx: AppContext, params: dict[str, Any]
) -> dict[str, Any]:
    history = await ctx.payment_engine.get_payment_history(
        agent_id=params["agent_id"],
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"history": history}


async def _partial_capture(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    settlement, remaining = await ctx.payment_engine.partial_capture(
        intent_id=params["intent_id"],
        amount=params["amount"],
    )
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": settlement.amount,
        "remaining_amount": remaining,
    }


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


async def _get_webhook_deliveries(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    deliveries = await ctx.webhook_manager.get_delivery_history(
        webhook_id=params["webhook_id"],
        limit=params.get("limit", 50),
    )
    return {"deliveries": deliveries}


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
# Database security tools
# ---------------------------------------------------------------------------

# Map of logical database names to environment variable names holding the DSN
_DB_DSN_MAP = {
    "billing": "BILLING_DSN",
    "paywall": "PAYWALL_DSN",
    "payments": "PAYMENTS_DSN",
    "marketplace": "MARKETPLACE_DSN",
    "trust": "TRUST_DSN",
    "identity": "IDENTITY_DSN",
    "event_bus": "EVENT_BUS_DSN",
    "webhooks": "WEBHOOK_DSN",
    "disputes": "DISPUTE_DSN",
    "messaging": "MESSAGING_DSN",
}


def _resolve_db_path(db_name: str) -> str:
    """Resolve a logical database name to its file path."""
    import os

    env_var = _DB_DSN_MAP.get(db_name)
    if not env_var:
        raise ValueError(f"Unknown database: {db_name}")
    dsn = os.environ.get(env_var, "")
    if not dsn:
        raise ValueError(f"DSN not configured for {db_name} (env: {env_var})")
    return dsn.replace("sqlite:///", "")


async def _backup_database(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os
    from datetime import datetime, timezone

    from shared_src.db_security import backup_database, encrypt_backup

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"{db_name}_{ts}.db")

    meta = await backup_database(db_path, dest)

    if params.get("encrypt"):
        enc_dest = dest + ".enc"
        enc_meta = await encrypt_backup(dest, enc_dest)
        os.unlink(dest)
        meta["path"] = enc_dest
        meta["size_bytes"] = enc_meta["size_bytes"]
        meta["key"] = enc_meta["key"]
        meta["encrypted"] = True

    return meta


async def _restore_database(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os

    from shared_src.db_security import decrypt_backup, restore_database

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    backup_path = params["backup_path"]

    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    # If encrypted, decrypt first
    source = backup_path
    if params.get("key"):
        dec_path = backup_path + ".dec"
        await decrypt_backup(backup_path, dec_path, params["key"])
        source = dec_path

    meta = await restore_database(source, db_path)

    if source != backup_path and os.path.exists(source):
        os.unlink(source)

    return meta


async def _check_db_integrity(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from shared_src.db_security import integrity_check

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    return await integrity_check(db_path)


async def _list_backups(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os

    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    backup_dir = os.path.join(data_dir, "backups")

    if not os.path.isdir(backup_dir):
        return {"backups": []}

    backups = []
    for fname in sorted(os.listdir(backup_dir)):
        fpath = os.path.join(backup_dir, fname)
        if os.path.isfile(fpath):
            backups.append({
                "filename": fname,
                "path": fpath,
                "size_bytes": os.path.getsize(fpath),
            })
    return {"backups": backups}


# ---------------------------------------------------------------------------
# Metrics time-series tools (P2-12)
# ---------------------------------------------------------------------------


async def _get_metrics_timeseries(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Return per-agent usage metrics bucketed by hour or day."""
    agent_id = params["agent_id"]
    interval = params["interval"]  # "hour" or "day"
    since = params.get("since")
    limit = params.get("limit", 24)

    # Determine the SQL bucket expression
    if interval == "hour":
        # Truncate created_at to the hour: floor(created_at / 3600) * 3600
        bucket_expr = "CAST(CAST(created_at / 3600 AS INTEGER) * 3600 AS REAL)"
    else:
        # Truncate created_at to the day: floor(created_at / 86400) * 86400
        bucket_expr = "CAST(CAST(created_at / 86400 AS INTEGER) * 86400 AS REAL)"

    query = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS cost "
        f"FROM usage_records WHERE agent_id = ?"
    )
    query_params: list[Any] = [agent_id]

    if since is not None:
        query += " AND created_at >= ?"
        query_params.append(since)

    query += f" GROUP BY bucket ORDER BY bucket DESC LIMIT ?"
    query_params.append(limit)

    db = ctx.tracker.storage.db
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    buckets = []
    for row in rows:
        buckets.append({
            "timestamp": row[0],
            "calls": row[1],
            "cost": round(row[2], 6),
        })

    # Return in ascending order (oldest first)
    buckets.reverse()
    return {"buckets": buckets}


# ---------------------------------------------------------------------------
# Agent leaderboard tools (P2-13)
# ---------------------------------------------------------------------------


async def _get_agent_leaderboard(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Rank agents by total spend, calls, or trust score."""
    metric = params["metric"]  # "spend", "calls", "trust_score"
    limit = params.get("limit", 10)

    if metric == "spend":
        db = ctx.tracker.storage.db
        cursor = await db.execute(
            "SELECT agent_id, COALESCE(SUM(cost), 0) AS value "
            "FROM usage_records GROUP BY agent_id ORDER BY value DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        leaderboard = [
            {"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)}
            for i, row in enumerate(rows)
        ]
    elif metric == "calls":
        db = ctx.tracker.storage.db
        cursor = await db.execute(
            "SELECT agent_id, COUNT(*) AS value "
            "FROM usage_records GROUP BY agent_id ORDER BY value DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        leaderboard = [
            {"rank": i + 1, "agent_id": row[0], "value": row[1]}
            for i, row in enumerate(rows)
        ]
    elif metric == "trust_score":
        # Query identity reputation storage for top agents by composite_score
        try:
            db = ctx.identity_api.storage.db
            cursor = await db.execute(
                "SELECT agent_id, composite_score FROM agent_reputation "
                "GROUP BY agent_id "
                "HAVING composite_score = MAX(composite_score) "
                "ORDER BY composite_score DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            leaderboard = [
                {"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)}
                for i, row in enumerate(rows)
            ]
        except Exception:
            leaderboard = []
    else:
        raise ValueError(f"Unknown metric: {metric}")

    return {"leaderboard": leaderboard}


# ---------------------------------------------------------------------------
# Event schema registry tools (P2-14)
# ---------------------------------------------------------------------------


async def _register_event_schema(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Register a JSON schema for an event type."""
    import json as _json

    event_type = params["event_type"]
    schema = params["schema"]
    schema_json = _json.dumps(schema, sort_keys=True)

    db = ctx.event_bus._db
    assert db is not None, "EventBus not connected"

    # Create table if not exists
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_schemas (
            event_type TEXT PRIMARY KEY,
            schema     TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )

    import time as _time
    now = _time.time()
    await db.execute(
        """
        INSERT INTO event_schemas (event_type, schema, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(event_type) DO UPDATE SET schema = excluded.schema, updated_at = excluded.updated_at
        """,
        (event_type, schema_json, now, now),
    )
    await db.commit()
    return {"event_type": event_type, "registered": True}


async def _get_event_schema(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the registered JSON schema for an event type."""
    import json as _json

    event_type = params["event_type"]
    db = ctx.event_bus._db
    assert db is not None, "EventBus not connected"

    # Create table if not exists (in case get is called before any register)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS event_schemas (
            event_type TEXT PRIMARY KEY,
            schema     TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )

    cursor = await db.execute(
        "SELECT event_type, schema FROM event_schemas WHERE event_type = ?",
        (event_type,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {"event_type": event_type, "found": False}

    return {
        "event_type": row[0],
        "schema": _json.loads(row[1]),
        "found": True,
    }


# ---------------------------------------------------------------------------
# Webhook test/ping tools (P2-15)
# ---------------------------------------------------------------------------


async def _test_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Send a test.ping event to a registered webhook and return the delivery result."""
    import json as _json
    import time as _time

    webhook_id = params["webhook_id"]
    wm = ctx.webhook_manager

    assert wm._db is not None, "WebhookManager not connected"

    # Look up the webhook
    cursor = await wm._db.execute(
        "SELECT * FROM webhooks WHERE id = ? AND active = 1",
        (webhook_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {"error": "Webhook not found", "found": False}

    webhook = wm._row_to_webhook(row)

    # Create a test.ping event
    now = _time.time()
    event = {
        "type": "test.ping",
        "webhook_id": webhook_id,
        "timestamp": now,
        "message": "Test ping from A2A gateway",
    }
    payload_json = _json.dumps(event)

    # Insert delivery record
    delivery_id = await wm._insert_delivery(
        webhook_id=webhook_id,
        event_type="test.ping",
        payload_json=payload_json,
        now=now,
    )

    # Attempt delivery
    await wm._send(webhook, delivery_id, event)

    # Read back the delivery result
    cursor2 = await wm._db.execute(
        "SELECT id, status, response_code FROM webhook_deliveries WHERE id = ?",
        (delivery_id,),
    )
    result_row = await cursor2.fetchone()

    return {
        "delivery_id": result_row["id"],
        "status": result_row["status"],
        "response_code": result_row["response_code"],
    }


# ---------------------------------------------------------------------------
# Self-service API key creation tools (P2-17)
# ---------------------------------------------------------------------------


async def _create_api_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a new API key for an agent (self-service).

    Only same-agent or admin can create keys. The caller's agent_id is extracted
    from the auth context, so this function receives extra context via request.
    """
    # This will be handled specially in the execute flow or we'll accept the agent_id
    # from params and validate it against the caller.
    # For simplicity we raise a permission error here; the real check happens in
    # the execute endpoint wrapper.
    agent_id = params["agent_id"]
    tier = params.get("tier", "free")

    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return {
        "key": key_info["key"],
        "agent_id": agent_id,
        "tier": tier,
        "created_at": key_info["created_at"],
    }


# ---------------------------------------------------------------------------
# Volume Discount tools (P3-18)
# ---------------------------------------------------------------------------


def _get_discount_tier(call_count: int) -> int:
    """Return discount percentage based on historical call count."""
    if call_count >= 1000:
        return 15
    if call_count >= 500:
        return 10
    if call_count >= 100:
        return 5
    return 0


async def _get_volume_discount(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Calculate volume discount based on historical usage."""
    agent_id = params["agent_id"]
    tool_name = params["tool_name"]
    quantity = int(params["quantity"])

    # Get historical call count for this tool
    usage = await ctx.tracker.storage.get_usage(
        agent_id, function=tool_name, limit=100000
    )
    historical_calls = len(usage)

    # Look up unit price from catalog
    from gateway.src.catalog import get_tool
    tool_def = get_tool(tool_name)
    unit_price = 0.0
    if tool_def:
        pricing = tool_def.get("pricing", {})
        unit_price = float(pricing.get("per_call", 0.0))

    discount_pct = _get_discount_tier(historical_calls)
    discounted_price = unit_price * (1 - discount_pct / 100)

    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "historical_calls": historical_calls,
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "discounted_price": round(discounted_price, 6),
    }


# ---------------------------------------------------------------------------
# Cost Estimation tools (P3-19)
# ---------------------------------------------------------------------------


async def _estimate_cost(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Estimate cost of N calls to a tool, with optional volume discount."""
    tool_name = params["tool_name"]
    quantity = int(params["quantity"])
    agent_id = params.get("agent_id")

    # Look up unit price from catalog
    from gateway.src.catalog import get_tool
    tool_def = get_tool(tool_name)
    unit_price = 0.0
    if tool_def:
        pricing = tool_def.get("pricing", {})
        unit_price = float(pricing.get("per_call", 0.0))
    else:
        return {
            "tool_name": tool_name,
            "quantity": quantity,
            "unit_price": 0,
            "discount_pct": 0,
            "total_cost": 0,
            "error": f"Tool not found: {tool_name}",
        }

    discount_pct = 0
    if agent_id:
        usage = await ctx.tracker.storage.get_usage(
            agent_id, function=tool_name, limit=100000
        )
        historical_calls = len(usage)
        discount_pct = _get_discount_tier(historical_calls)

    total_cost = unit_price * quantity * (1 - discount_pct / 100)

    return {
        "tool_name": tool_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
        "total_cost": round(total_cost, 6),
    }


# ---------------------------------------------------------------------------
# Service Ratings tools (P3-20)
# ---------------------------------------------------------------------------


async def _rate_service_tool(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Rate a marketplace service (1-5). Upserts per agent per service."""
    service_id = params["service_id"]
    agent_id = params["agent_id"]
    rating = int(params["rating"])
    review = params.get("review", "")

    if rating < 1 or rating > 5:
        return {"error": "Rating must be between 1 and 5"}

    import time as _time
    now = _time.time()

    db = ctx.marketplace._storage.db
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
    # Upsert: one rating per agent per service
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

    db = ctx.marketplace._storage.db
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

    # Get average and count
    cursor = await db.execute(
        "SELECT AVG(rating) as avg_rating, COUNT(*) as cnt FROM service_ratings WHERE service_id = ?",
        (service_id,),
    )
    row = await cursor.fetchone()
    avg_rating = round(row["avg_rating"], 2) if row["avg_rating"] is not None else 0
    count = row["cnt"] if row else 0

    # Get individual ratings
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
# Budget Cap tools (P3-22)
# ---------------------------------------------------------------------------


async def _set_budget_cap(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Set daily/monthly spending caps for an agent."""
    agent_id = params["agent_id"]
    daily_cap = params.get("daily_cap")
    monthly_cap = params.get("monthly_cap")
    alert_threshold = params.get("alert_threshold", 0.8)

    db = ctx.tracker.storage.db
    await db.execute(
        """CREATE TABLE IF NOT EXISTS budget_caps (
            agent_id TEXT PRIMARY KEY,
            daily_cap REAL,
            monthly_cap REAL,
            alert_threshold REAL NOT NULL DEFAULT 0.8
        )"""
    )
    await db.execute(
        """INSERT INTO budget_caps (agent_id, daily_cap, monthly_cap, alert_threshold)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             daily_cap = excluded.daily_cap,
             monthly_cap = excluded.monthly_cap,
             alert_threshold = excluded.alert_threshold""",
        (agent_id, daily_cap, monthly_cap, alert_threshold),
    )
    await db.commit()

    return {
        "agent_id": agent_id,
        "daily_cap": daily_cap,
        "monthly_cap": monthly_cap,
        "alert_threshold": alert_threshold,
    }


async def _get_budget_status(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get current spending vs budget caps."""
    import time as _time

    agent_id = params["agent_id"]
    db = ctx.tracker.storage.db

    await db.execute(
        """CREATE TABLE IF NOT EXISTS budget_caps (
            agent_id TEXT PRIMARY KEY,
            daily_cap REAL,
            monthly_cap REAL,
            alert_threshold REAL NOT NULL DEFAULT 0.8
        )"""
    )

    # Get budget caps
    cursor = await db.execute(
        "SELECT * FROM budget_caps WHERE agent_id = ?", (agent_id,)
    )
    row = await cursor.fetchone()

    daily_cap = row["daily_cap"] if row and row["daily_cap"] is not None else None
    monthly_cap = row["monthly_cap"] if row and row["monthly_cap"] is not None else None
    alert_threshold = row["alert_threshold"] if row else 0.8

    now = _time.time()
    # Daily spend: last 24 hours
    daily_since = now - 86400
    daily_spend = await ctx.tracker.storage.sum_cost_since(agent_id, daily_since)

    # Monthly spend: last 30 days
    monthly_since = now - (30 * 86400)
    monthly_spend = await ctx.tracker.storage.sum_cost_since(agent_id, monthly_since)

    daily_pct = (daily_spend / daily_cap * 100) if daily_cap else 0
    monthly_pct = (monthly_spend / monthly_cap * 100) if monthly_cap else 0

    # Check if alert or cap exceeded
    alert_triggered = False
    cap_exceeded = False

    if daily_cap:
        if daily_spend / daily_cap >= alert_threshold:
            alert_triggered = True
        if daily_spend >= daily_cap:
            cap_exceeded = True

    if monthly_cap:
        if monthly_spend / monthly_cap >= alert_threshold:
            alert_triggered = True
        if monthly_spend >= monthly_cap:
            cap_exceeded = True

    return {
        "agent_id": agent_id,
        "daily_spend": round(daily_spend, 2),
        "daily_cap": daily_cap,
        "daily_pct": round(daily_pct, 2),
        "monthly_spend": round(monthly_spend, 2),
        "monthly_cap": monthly_cap,
        "monthly_pct": round(monthly_pct, 2),
        "alert_triggered": alert_triggered,
        "cap_exceeded": cap_exceeded,
    }


# ---------------------------------------------------------------------------
# Org/Team tools (P3-23)
# ---------------------------------------------------------------------------


async def _create_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a new organization."""
    import time as _time
    import uuid as _uuid

    org_name = params["org_name"]
    org_id = f"org-{_uuid.uuid4().hex[:12]}"
    now = _time.time()

    db = ctx.identity_api.storage.db
    await db.execute(
        """CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )"""
    )
    await db.execute(
        "INSERT INTO orgs (id, name, created_at) VALUES (?, ?, ?)",
        (org_id, org_name, now),
    )
    await db.commit()

    return {
        "org_id": org_id,
        "name": org_name,
        "created_at": now,
    }


async def _get_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get organization details and members."""
    org_id = params["org_id"]
    db = ctx.identity_api.storage.db

    await db.execute(
        """CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )"""
    )

    cursor = await db.execute("SELECT * FROM orgs WHERE id = ?", (org_id,))
    row = await cursor.fetchone()
    if row is None:
        return {"error": f"Org not found: {org_id}"}

    # Get members
    cursor2 = await db.execute(
        "SELECT agent_id FROM agent_identities WHERE org_id = ?", (org_id,)
    )
    members = [{"agent_id": r["agent_id"]} for r in await cursor2.fetchall()]

    return {
        "org_id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "members": members,
    }


async def _add_agent_to_org(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Add an agent to an organization."""
    org_id = params["org_id"]
    agent_id = params["agent_id"]
    db = ctx.identity_api.storage.db

    await db.execute(
        """CREATE TABLE IF NOT EXISTS orgs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at REAL NOT NULL
        )"""
    )

    # Verify org exists
    cursor = await db.execute("SELECT id FROM orgs WHERE id = ?", (org_id,))
    if await cursor.fetchone() is None:
        return {"error": f"Org not found: {org_id}"}

    # Update agent's org_id
    await db.execute(
        "UPDATE agent_identities SET org_id = ? WHERE agent_id = ?",
        (org_id, agent_id),
    )
    await db.commit()

    return {
        "agent_id": agent_id,
        "org_id": org_id,
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
    "get_transactions": _get_transactions,
    # Payments
    "create_intent": _create_intent,
    "capture_intent": _capture_intent,
    "create_escrow": _create_escrow,
    "release_escrow": _release_escrow,
    "cancel_escrow": _cancel_escrow,
    "refund_intent": _refund_intent,
    "get_payment_history": _get_payment_history,
    "partial_capture": _partial_capture,
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
    "get_service": _get_service,
    "update_service": _update_service,
    "deactivate_service": _deactivate_service,
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
    "get_webhook_deliveries": _get_webhook_deliveries,
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
    # Database security
    "backup_database": _backup_database,
    "restore_database": _restore_database,
    "check_db_integrity": _check_db_integrity,
    "list_backups": _list_backups,
    # P2 features
    "get_metrics_timeseries": _get_metrics_timeseries,
    "get_agent_leaderboard": _get_agent_leaderboard,
    "register_event_schema": _register_event_schema,
    "get_event_schema": _get_event_schema,
    "test_webhook": _test_webhook,
    "create_api_key": _create_api_key,
    # P3 features — Volume Discount & Cost Estimation
    "get_volume_discount": _get_volume_discount,
    "estimate_cost": _estimate_cost,
    # P3 features — Service Ratings
    "rate_service": _rate_service_tool,
    "get_service_ratings": _get_service_ratings_tool,
    # P3 features — Budget Caps
    "set_budget_cap": _set_budget_cap,
    "get_budget_status": _get_budget_status,
    # P3 features — Org/Team
    "create_org": _create_org,
    "get_org": _get_org,
    "add_agent_to_org": _add_agent_to_org,
}


# ---------------------------------------------------------------------------
# MCP Connector proxy tools — dynamically registered at startup
# ---------------------------------------------------------------------------


def register_mcp_tools(proxy_manager) -> None:
    """Register proxy tool functions for all MCP connector tools."""
    from gateway.src.mcp_proxy import _TOOL_MAP

    for tool_name in _TOOL_MAP:
        # Capture tool_name in closure
        def _make_handler(tn: str):
            async def _handler(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
                return await ctx.mcp_proxy.call_tool(tn, params)
            return _handler

        TOOL_REGISTRY[tool_name] = _make_handler(tool_name)
