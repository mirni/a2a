"""Payment, escrow, subscription, split, and dispute tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext


# ---------------------------------------------------------------------------
# Payment Intents
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
    return {"id": intent.id, "status": intent.status.value, "amount": float(intent.amount)}


async def _capture_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    settlement = await ctx.payment_engine.capture(params["intent_id"])
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": float(settlement.amount),
    }


async def _refund_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Refund a payment intent.

    - If pending: void it (no funds moved).
    - If settled: create a reverse transfer from payee to payer.
    """
    intent = await ctx.payment_engine.get_intent(params["intent_id"])

    if intent.status.value == "pending":
        voided = await ctx.payment_engine.void(intent.id)
        return {"id": voided.id, "status": "voided", "amount": float(voided.amount)}

    if intent.status.value == "settled":
        await ctx.tracker.wallet.withdraw(
            intent.payee, float(intent.amount), description=f"refund:{intent.id}"
        )
        await ctx.tracker.wallet.deposit(
            intent.payer, float(intent.amount), description=f"refund:{intent.id}"
        )
        return {"id": intent.id, "status": "refunded", "amount": float(intent.amount)}

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
        "amount": float(settlement.amount),
        "remaining_amount": remaining,
    }


# ---------------------------------------------------------------------------
# Escrow
# ---------------------------------------------------------------------------


async def _create_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    escrow = await ctx.payment_engine.create_escrow(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        timeout_hours=params.get("timeout_hours"),
        metadata=params.get("metadata"),
    )
    return {"id": escrow.id, "status": escrow.status.value, "amount": float(escrow.amount)}


async def _release_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    settlement = await ctx.payment_engine.release_escrow(params["escrow_id"])
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": float(settlement.amount),
    }


async def _cancel_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    escrow = await ctx.payment_engine.refund_escrow(params["escrow_id"])
    return {
        "id": escrow.id,
        "status": escrow.status.value,
        "amount": float(escrow.amount),
    }


# ---------------------------------------------------------------------------
# Performance-gated Escrow
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
        "amount": float(escrow.amount),
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

    claims = await ctx.identity_api.get_verified_claims(escrow.payee)
    for claim in claims:
        if claim.metric_name == metric_name:
            if claim.claim_type == "gte" and claim.bound_value >= threshold:
                settlement = await ctx.payment_engine.release_escrow(escrow.id)
                return {"released": True, "settlement_id": settlement.id}
            if claim.claim_type == "lte" and claim.bound_value <= threshold:
                settlement = await ctx.payment_engine.release_escrow(escrow.id)
                return {"released": True, "settlement_id": settlement.id}

    return {"released": False, "reason": "Metric threshold not met"}


# ---------------------------------------------------------------------------
# Subscriptions
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
        "amount": float(sub.amount),
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
        "amount": float(sub.amount),
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
# Multi-party Splits
# ---------------------------------------------------------------------------


async def _create_split_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a payment split across multiple payees.

    Splits must sum to 100%. Withdraws full amount from payer, deposits to each payee.
    """
    payer = params["payer"]
    amount = float(params["amount"])
    splits = params["splits"]
    description = params.get("description", "")

    from gateway.src.tool_errors import ToolValidationError

    total_pct = sum(s["percentage"] for s in splits)
    if abs(total_pct - 100) > 0.01:
        raise ToolValidationError(f"Split percentages must sum to 100, got {total_pct}")

    await ctx.tracker.wallet.withdraw(payer, amount, description=f"split:{description}")

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
# Disputes
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
