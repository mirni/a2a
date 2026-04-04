"""Tests for P1 #7: Float→string in payment responses.

Payment amounts must be serialized as strings to avoid float precision loss.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.src.tools.payments import (
    _create_escrow,
    _create_intent,
    _create_subscription,
    _get_escrow,
    _get_intent,
    _get_subscription,
    _refund_settlement,
)

pytestmark = pytest.mark.asyncio


def _make_intent(amount: Decimal = Decimal("10.50")):
    intent = MagicMock()
    intent.id = "intent-1"
    intent.status.value = "pending"
    intent.payer = "alice"
    intent.payee = "bob"
    intent.amount = amount
    intent.description = "test"
    intent.created_at = 1000.0
    return intent


def _make_escrow(amount: Decimal = Decimal("10.50")):
    escrow = MagicMock()
    escrow.id = "escrow-1"
    escrow.status.value = "held"
    escrow.payer = "alice"
    escrow.payee = "bob"
    escrow.amount = amount
    escrow.description = "test"
    escrow.created_at = 1000.0
    return escrow


class TestPaymentAmountSerialization:
    """Payment response amounts must be strings, not floats."""

    async def test_get_intent_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        ctx.payment_engine.get_intent.return_value = _make_intent(Decimal("10.50"))

        result = await _get_intent(ctx, {"intent_id": "i1"})
        assert isinstance(result["amount"], str)
        assert result["amount"] == "10.50"

    async def test_get_escrow_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        ctx.payment_engine.get_escrow.return_value = _make_escrow(Decimal("25.99"))

        result = await _get_escrow(ctx, {"escrow_id": "e1"})
        assert isinstance(result["amount"], str)
        assert result["amount"] == "25.99"

    async def test_create_intent_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        intent = _make_intent(Decimal("99.99"))
        ctx.payment_engine.create_intent.return_value = intent

        result = await _create_intent(ctx, {"payer": "alice", "payee": "bob", "amount": 99.99})
        assert isinstance(result["amount"], str)

    async def test_create_escrow_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        escrow = _make_escrow(Decimal("50.00"))
        ctx.payment_engine.create_escrow.return_value = escrow

        result = await _create_escrow(ctx, {"payer": "alice", "payee": "bob", "amount": 50.00})
        assert isinstance(result["amount"], str)

    async def test_create_subscription_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        sub = MagicMock()
        sub.id = "sub-1"
        sub.status.value = "active"
        sub.amount = Decimal("9.99")
        sub.interval.value = "monthly"
        sub.next_charge_at = 2000.0
        ctx.payment_engine.create_subscription.return_value = sub

        result = await _create_subscription(
            ctx, {"payer": "alice", "payee": "bob", "amount": 9.99, "interval": "monthly"}
        )
        assert isinstance(result["amount"], str)

    async def test_get_subscription_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        sub = MagicMock()
        sub.id = "sub-1"
        sub.payer = "alice"
        sub.payee = "bob"
        sub.amount = Decimal("9.99")
        sub.interval.value = "monthly"
        sub.status.value = "active"
        sub.next_charge_at = 2000.0
        sub.charge_count = 3
        sub.created_at = 1000.0
        ctx.payment_engine.get_subscription.return_value = sub

        result = await _get_subscription(ctx, {"subscription_id": "s1"})
        assert isinstance(result["amount"], str)

    async def test_refund_settlement_amount_is_string(self):
        ctx = MagicMock()
        ctx.payment_engine = AsyncMock()
        refund = MagicMock()
        refund.id = "ref-1"
        refund.settlement_id = "set-1"
        refund.amount = Decimal("15.00")
        refund.reason = "test"
        refund.status.value = "completed"
        ctx.payment_engine.refund_settlement.return_value = refund

        result = await _refund_settlement(ctx, {"settlement_id": "s1"})
        assert isinstance(result["amount"], str)
