"""Shared tool-handler validators.

P2-1: centralises ownership checks and money formatting that were
copy-pasted across identity.py, gatekeeper.py, and payments.py.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from gateway.src.tool_errors import ToolForbiddenError

ADMIN_TIER = "admin"


def check_caller_owns_agent_id(params: dict[str, Any]) -> None:
    """Raise ToolForbiddenError if caller is not admin and agent_id != caller."""
    caller = params.get("_caller_agent_id")
    tier = params.get("_caller_tier")
    target = params.get("agent_id")
    if tier == ADMIN_TIER or caller is None or target is None:
        return
    if caller != target:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


def check_caller_owns_job(job_agent_id: str, params: dict[str, Any]) -> None:
    """Raise ToolForbiddenError if caller does not own the job's agent_id."""
    caller = params.get("_caller_agent_id")
    tier = params.get("_caller_tier")
    if tier == ADMIN_TIER or caller is None:
        return
    if caller != job_agent_id:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


def check_intent_ownership(
    caller: str,
    tier: str,
    intent: Any,
    *,
    payer_only: bool = False,
) -> None:
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


def format_money(amount: float | Decimal | str) -> str:
    """Render a monetary amount as a 2-decimal string.

    Audit HIGH-3 (v1.2.1): the previous code used ``str(float)`` which
    returned ``"0.0246"`` for a 2% fee on 1.23 and ``"5.0"`` for a 2%
    fee on 250.00 — both broke client-side reconciliation. All money
    returned to clients must go through this helper so we always emit
    exactly two decimal places.
    """
    d = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
