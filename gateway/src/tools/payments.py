"""Payment, escrow, subscription, split, and dispute tool functions."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from gateway.src.authorization import ADMIN_TIER
from gateway.src.lifespan import AppContext
from gateway.src.tool_errors import ToolForbiddenError, ToolValidationError


def _format_money(amount: float | Decimal | str) -> str:
    """Render a monetary amount as a 2-decimal string.

    Audit HIGH-3 (v1.2.1): the previous code used ``str(float)`` which
    returned ``"0.0246"`` for a 2% fee on 1.23 and ``"5.0"`` for a 2%
    fee on 250.00 — both broke client-side reconciliation. All money
    returned to clients must go through this helper so we always emit
    exactly two decimal places.
    """
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _check_intent_ownership(caller: str, tier: str, intent, *, payer_only: bool = False) -> None:
    """Verify the caller is authorized to act on the intent.

    Args:
        payer_only: If True, only the *payer* is authorized (used for capture/
            void — operations that debit the payer's wallet). If False, either
            payer or payee may access (used for read operations like get_intent).

    Admin-tier callers bypass this check.
    Raises ToolForbiddenError if the caller is not authorized.
    """
    if tier == ADMIN_TIER:
        return
    if payer_only:
        if caller != intent.payer:
            raise ToolForbiddenError("Forbidden: only the payer can perform this action")
    else:
        if caller not in (intent.payer, intent.payee):
            raise ToolForbiddenError("Forbidden: you do not have access to this resource")


def _check_escrow_ownership(caller: str, tier: str, escrow) -> None:
    """Verify the caller is a party to the escrow (payer or payee).

    Admin-tier callers bypass this check.
    Raises ToolForbiddenError if the caller is not involved.
    """
    if tier == ADMIN_TIER:
        return
    if caller not in (escrow.payer, escrow.payee):
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


def _check_escrow_payer(caller: str, tier: str, escrow) -> None:
    """Verify the caller is the escrow payer (not payee).

    Only the payer (or admin) may cancel an escrow.
    Raises ToolForbiddenError if the caller is not the payer.
    """
    if tier == ADMIN_TIER:
        return
    if caller != escrow.payer:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


_VALID_CURRENCIES = {"CREDITS", "USD", "EUR", "GBP", "BTC", "ETH"}


def _validate_currency(currency: str) -> str:
    """Validate currency code and return it, raising ToolValidationError on invalid."""
    if currency not in _VALID_CURRENCIES:
        raise ToolValidationError(f"Invalid currency '{currency}'; must be one of {sorted(_VALID_CURRENCIES)}")
    return currency


# ---------------------------------------------------------------------------
# Payment Intents
# ---------------------------------------------------------------------------


async def _get_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    intent = await ctx.payment_engine.get_intent(params["intent_id"])
    return {
        "id": intent.id,
        "status": intent.status.value,
        "payer": intent.payer,
        "payee": intent.payee,
        "amount": str(intent.amount),
        "description": intent.description,
        "created_at": intent.created_at,
    }


async def _get_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    escrow = await ctx.payment_engine.get_escrow(params["escrow_id"])
    return {
        "id": escrow.id,
        "status": escrow.status.value,
        "payer": escrow.payer,
        "payee": escrow.payee,
        "amount": str(escrow.amount),
        "description": escrow.description,
        "created_at": escrow.created_at,
    }


async def _create_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    currency = _validate_currency(params.get("currency", "CREDITS"))
    intent = await ctx.payment_engine.create_intent(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        idempotency_key=params.get("idempotency_key"),
        metadata=params.get("metadata"),
        currency=currency,
    )
    # Audit H3 (v1.2.1): disclose the gateway fee charged on this intent
    # so clients can reconcile charges. Must be rendered with 2 decimal
    # places — `str(float)` leaks float representation (``0.0246``) and
    # loses trailing zeros (``5.0``), breaking reconciliation.
    return {
        "id": intent.id,
        "status": intent.status.value,
        "amount": str(intent.amount),
        "currency": currency,
        "gateway_fee": _format_money(_compute_create_intent_gateway_fee(float(params["amount"]))),
    }


async def _capture_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    caller = params.get("_caller_agent_id", "")
    tier = params.get("_caller_tier", "")
    intent = await ctx.payment_engine.get_intent(params["intent_id"])
    _check_intent_ownership(caller, tier, intent, payer_only=True)
    settlement = await ctx.payment_engine.capture(
        params["intent_id"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": str(settlement.amount),
    }


def _compute_create_intent_gateway_fee(amount: float) -> float:
    """Recompute the gateway fee charged at create_intent time.

    Audit H3: the fee is deterministic (percentage of intent amount, clamped to
    [min_fee, max_fee] per the pricing config). We recompute rather than store
    it on the intent to keep the schema stable.
    """
    from gateway.src.catalog import get_tool
    from gateway.src.deps.billing import calculate_tool_cost

    tool_def = get_tool("create_intent")
    if not tool_def:
        return 0.0
    return calculate_tool_cost(tool_def.get("pricing", {}), {"amount": float(amount)})


# v1.2.4 audit HIGH-2 (v1.2.3): a full refund must return the customer
# whole. The 2% gateway fee charged at create_intent is credited back
# on refund so the payer wallet delta is exactly zero. The response
# still exposes ``fee_policy`` for integrator reconciliation docs, now
# pointing at ADR-012 (supersedes ADR-011).
_REFUND_FEE_POLICY: dict[str, str] = {
    "name": "refund_full_amount",
    "adr": "ADR-012",
    "url": "https://docs.greenhelix.net/adr/012-refund-fee-policy",
    "summary": (
        "Full refunds return the customer whole: the 2% gateway fee is "
        "reversed alongside the principal. Supersedes ADR-011."
    ),
    "supersedes": "ADR-011",
}


async def _refund_intent(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Refund a payment intent.

    - If pending: void it (no funds moved). Gateway fee charged at
      ``create_intent`` is reversed to the payer.
    - If settled: create a reverse transfer from payee to payer AND
      credit the gateway fee back to the payer wallet.

    Audit v1.2.3 HIGH-2: a full refund of a 50.00 intent must restore
    the payer's wallet by exactly 50.00 — including the 2% gateway fee
    that was charged at ``create_intent`` time. The response exposes
    ``fee_refunded=True`` / ``fee_retained="0.00"`` (legacy shape) and
    a ``fee_policy`` object pointing at ADR-012 so integrators can cite
    a stable URL in their reconciliation docs.
    """
    caller = params.get("_caller_agent_id", "")
    tier = params.get("_caller_tier", "")
    intent = await ctx.payment_engine.get_intent(params["intent_id"])
    _check_intent_ownership(caller, tier, intent)

    gateway_fee = _compute_create_intent_gateway_fee(float(intent.amount))
    # New policy (v1.2.4): the fee charged at create_intent is refunded.
    fee_refunded = True
    fee_retained = 0.0
    currency = (intent.metadata or {}).get("currency", "CREDITS")

    async def _credit_fee_back() -> None:
        """Credit the create_intent gateway fee back to the payer wallet.

        Guarded so a missing wallet (e.g. test fixture deleted the
        payer mid-flow) does not turn the refund into a 500. Any
        error here is logged via the wallet layer.
        """
        if gateway_fee <= 0:
            return
        try:
            await ctx.tracker.wallet.deposit(
                intent.payer,
                float(gateway_fee),
                description=f"refund-fee:{intent.id}",
                currency=currency,
            )
        except Exception:  # pragma: no cover - defensive
            # Log via the standard gateway logger and fall through; the
            # principal refund still happened and will be reconciled.
            import logging as _logging

            _logging.getLogger("a2a.gateway").exception(
                "refund_intent: failed to credit gateway_fee back to %s",
                intent.payer,
            )

    if intent.status.value == "pending":
        voided = await ctx.payment_engine.void(intent.id, idempotency_key=params.get("idempotency_key"))
        await _credit_fee_back()
        return {
            "id": voided.id,
            "status": "voided",
            "amount": str(voided.amount),
            "gateway_fee": _format_money(gateway_fee),
            "fee_refunded": fee_refunded,
            "fee_retained": _format_money(fee_retained),
            "fee_policy": dict(_REFUND_FEE_POLICY),
        }

    # Idempotency: if already voided and idempotency_key provided, return success
    if intent.status.value == "voided" and params.get("idempotency_key"):
        return {
            "id": intent.id,
            "status": "voided",
            "amount": str(intent.amount),
            "gateway_fee": _format_money(gateway_fee),
            "fee_refunded": fee_refunded,
            "fee_retained": _format_money(fee_retained),
            "fee_policy": dict(_REFUND_FEE_POLICY),
        }

    if intent.status.value == "settled":
        await ctx.tracker.wallet.withdraw(
            intent.payee,
            float(intent.amount),
            description=f"refund:{intent.id}",
            currency=currency,
        )
        await ctx.tracker.wallet.deposit(
            intent.payer,
            float(intent.amount),
            description=f"refund:{intent.id}",
            currency=currency,
        )
        await _credit_fee_back()
        return {
            "id": intent.id,
            "status": "refunded",
            "amount": str(intent.amount),
            "gateway_fee": _format_money(gateway_fee),
            "fee_refunded": fee_refunded,
            "fee_retained": _format_money(fee_retained),
            "fee_policy": dict(_REFUND_FEE_POLICY),
        }

    from payments_src.engine import InvalidStateError

    raise InvalidStateError(f"Cannot refund intent in state '{intent.status.value}'")


async def _get_payment_history(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    history = await ctx.payment_engine.get_payment_history(
        agent_id=params["agent_id"],
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"history": history}


async def _partial_capture(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    caller = params.get("_caller_agent_id", "")
    tier = params.get("_caller_tier", "")
    intent = await ctx.payment_engine.get_intent(params["intent_id"])
    _check_intent_ownership(caller, tier, intent, payer_only=True)
    settlement, remaining = await ctx.payment_engine.partial_capture(
        intent_id=params["intent_id"],
        amount=params["amount"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": str(settlement.amount),
        "remaining_amount": remaining,
    }


async def _list_intents(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """List payment intents for an agent, optionally filtered by status."""
    intents = await ctx.payment_engine.storage.list_intents(
        agent_id=params["agent_id"],
        status=params.get("status"),
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )
    return {"intents": intents, "count": len(intents)}


# ---------------------------------------------------------------------------
# Escrow
# ---------------------------------------------------------------------------


async def _list_escrows(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """List escrows for an agent, optionally filtered by status."""
    escrows = await ctx.payment_engine.storage.list_escrows(
        agent_id=params["agent_id"],
        status=params.get("status"),
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )
    return {"escrows": escrows, "count": len(escrows)}


async def _create_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    currency = _validate_currency(params.get("currency", "CREDITS"))
    escrow = await ctx.payment_engine.create_escrow(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        description=params.get("description", ""),
        timeout_hours=params.get("timeout_hours"),
        metadata=params.get("metadata"),
        idempotency_key=params.get("idempotency_key"),
        currency=currency,
    )
    return {
        "id": escrow.id,
        "status": escrow.status.value,
        "amount": str(escrow.amount),
        "currency": currency,
    }


async def _release_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    caller = params.get("_caller_agent_id", "")
    tier = params.get("_caller_tier", "")
    escrow = await ctx.payment_engine.get_escrow(params["escrow_id"])
    _check_escrow_ownership(caller, tier, escrow)
    settlement = await ctx.payment_engine.release_escrow(
        params["escrow_id"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "id": settlement.id,
        "status": "settled",
        "amount": str(settlement.amount),
    }


async def _cancel_escrow(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    caller = params.get("_caller_agent_id", "")
    tier = params.get("_caller_tier", "")
    escrow = await ctx.payment_engine.get_escrow(params["escrow_id"])
    _check_escrow_payer(caller, tier, escrow)
    escrow = await ctx.payment_engine.refund_escrow(
        params["escrow_id"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "id": escrow.id,
        "status": escrow.status.value,
        "amount": str(escrow.amount),
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
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "escrow_id": escrow.id,
        "status": escrow.status.value,
        "amount": str(escrow.amount),
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
    currency = _validate_currency(params.get("currency", "CREDITS"))
    sub = await ctx.payment_engine.create_subscription(
        payer=params["payer"],
        payee=params["payee"],
        amount=params["amount"],
        interval=params["interval"],
        description=params.get("description", ""),
        metadata=params.get("metadata"),
        idempotency_key=params.get("idempotency_key"),
        currency=currency,
    )
    return {
        "id": sub.id,
        "status": sub.status.value,
        "amount": str(sub.amount),
        "interval": sub.interval.value,
        "next_charge_at": sub.next_charge_at,
        "currency": currency,
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
        "amount": str(sub.amount),
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
    sub = await ctx.payment_engine.reactivate_subscription(
        params["subscription_id"],
        idempotency_key=params.get("idempotency_key"),
    )
    return {"id": sub.id, "status": sub.status.value}


async def _process_due_subscriptions(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
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
    import json
    from decimal import Decimal

    payer = params["payer"]
    amount = float(params["amount"])
    splits = params["splits"]
    description = params.get("description", "")
    currency = _validate_currency(params.get("currency", "CREDITS"))
    idempotency_key = params.get("idempotency_key")

    # Check idempotency BEFORE executing the split
    if idempotency_key is not None:
        existing = await ctx.tracker.storage.get_transaction_by_idempotency_key(
            idempotency_key,
        )
        if existing is not None:
            snapshot = existing.get("result_snapshot")
            if snapshot:
                return json.loads(snapshot)

    total_pct = sum(s["percentage"] for s in splits)
    if abs(total_pct - 100) > 0.01:
        raise ToolValidationError(f"Split percentages must sum to 100, got {total_pct}")

    await ctx.tracker.wallet.withdraw(
        payer,
        amount,
        description=f"split:{description}",
        currency=currency,
    )

    settlements = []
    for split in splits:
        payee = split["payee"]
        share = float(Decimal(str(amount)) * Decimal(str(split["percentage"])) / Decimal("100"))
        await ctx.tracker.wallet.deposit(payee, share, description=f"split_from:{payer}", currency=currency)
        settlements.append({"payee": payee, "amount": share, "percentage": split["percentage"]})

    result = {
        "status": "settled",
        "payer": payer,
        "total_amount": amount,
        "currency": currency,
        "settlements": settlements,
    }

    # Record idempotency marker
    if idempotency_key is not None:
        await ctx.tracker.storage.record_transaction(
            payer,
            -amount,
            "split_intent",
            description,
            idempotency_key=idempotency_key,
            result_snapshot=json.dumps(result),
        )

    return result


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
    # Verify caller is the actual respondent
    caller = params.get("_caller_agent_id")
    if caller:
        dispute = await ctx.dispute_engine.get_dispute(params["dispute_id"])
        if dispute["respondent"] != caller:
            from gateway.src.tool_errors import ToolForbiddenError

            raise ToolForbiddenError("Forbidden: you do not have access to this resource")
    return await ctx.dispute_engine.respond_to_dispute(
        dispute_id=params["dispute_id"],
        respondent=params["respondent"],
        response=params["response"],
    )


async def _get_dispute(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    return await ctx.dispute_engine.get_dispute(params["dispute_id"])


async def _list_disputes(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    disputes = await ctx.dispute_engine.list_disputes(
        agent_id=params["agent_id"],
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )
    return {"disputes": disputes}


async def _resolve_dispute(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    # Security: override resolved_by with authenticated caller to prevent impersonation.
    caller = params.get("_caller_agent_id", params["resolved_by"])
    return await ctx.dispute_engine.resolve_dispute(
        dispute_id=params["dispute_id"],
        resolution=params["resolution"],
        resolved_by=caller,
        notes=params.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Settlement Refunds
# ---------------------------------------------------------------------------


async def _refund_settlement(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Refund a settled payment (full or partial).

    If amount is omitted, refunds the full remaining balance.
    """
    from decimal import Decimal

    amount = None
    if "amount" in params and params["amount"] is not None:
        amount = Decimal(str(params["amount"]))

    refund = await ctx.payment_engine.refund_settlement(
        settlement_id=params["settlement_id"],
        amount=amount,
        reason=params.get("reason", ""),
        idempotency_key=params.get("idempotency_key"),
    )
    return {
        "id": refund.id,
        "settlement_id": refund.settlement_id,
        "amount": str(refund.amount),
        "reason": refund.reason,
        "status": refund.status.value,
    }
