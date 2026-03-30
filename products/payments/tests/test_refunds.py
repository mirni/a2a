"""Tests for settlement refund functionality.

Covers:
- Full refund of settled payment reverses funds
- Partial refund deducts correct amount
- Multiple partial refunds up to original amount
- Refund exceeding remaining amount raises error
- Refund of non-existent settlement raises error
- Refund of already-fully-refunded settlement raises error
- Refund model has correct schema_extra
- Decimal precision is maintained
- Negative tests: amount=0, negative amount
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from payments.engine import (
    InvalidStateError,
    PaymentError,
    SettlementNotFoundError,
)
from payments.models import Refund, RefundStatus, SettlementStatus

# ---------------------------------------------------------------------------
# Refund model unit tests
# ---------------------------------------------------------------------------


class TestRefundModel:
    def test_refund_has_schema_extra(self):
        """Refund model must include json_schema_extra example per CLAUDE.md."""
        schema = Refund.model_json_schema()
        assert "examples" in schema or "examples" in Refund.model_config.get("json_schema_extra", {})

    def test_refund_creation_defaults(self):
        refund = Refund(
            settlement_id="settle-123",
            amount=Decimal("25.00"),
            reason="Customer request",
        )
        assert refund.id  # auto-generated
        assert refund.settlement_id == "settle-123"
        assert refund.amount == Decimal("25.00")
        assert refund.reason == "Customer request"
        assert refund.status == RefundStatus.COMPLETED
        assert refund.created_at > 0

    def test_refund_amount_is_decimal(self):
        refund = Refund(
            settlement_id="settle-123",
            amount=Decimal("10.50"),
        )
        assert isinstance(refund.amount, Decimal)

    def test_refund_extra_fields_forbidden(self):
        """extra='forbid' must be set on request models."""
        with pytest.raises(Exception):
            Refund(
                settlement_id="settle-123",
                amount=Decimal("10.00"),
                bogus_field="not_allowed",
            )

    def test_refund_model_dump_amount_serialization(self):
        refund = Refund(
            settlement_id="settle-123",
            amount=Decimal("33.33"),
        )
        d = refund.model_dump()
        assert d["amount"] == float(Decimal("33.33"))

    def test_refund_status_values(self):
        assert RefundStatus.COMPLETED.value == "completed"

    def test_settlement_status_values(self):
        assert SettlementStatus.SETTLED.value == "settled"
        assert SettlementStatus.REFUNDED.value == "refunded"
        assert SettlementStatus.PARTIALLY_REFUNDED.value == "partially_refunded"


# ---------------------------------------------------------------------------
# Full refund
# ---------------------------------------------------------------------------


class TestFullRefund:
    async def test_full_refund_reverses_funds(self, engine, funded_wallets):
        """Full refund should reverse the entire settlement amount."""
        wallet, _, _ = funded_wallets
        # Create and capture intent (agent-a pays agent-b)
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        # Verify pre-refund balances
        assert await wallet.get_balance("agent-a") == 900.0
        assert await wallet.get_balance("agent-b") == 600.0

        # Full refund
        refund = await engine.refund_settlement(settlement.id)

        # Verify post-refund balances
        assert await wallet.get_balance("agent-a") == 1000.0
        assert await wallet.get_balance("agent-b") == 500.0

        # Verify refund details
        assert refund.settlement_id == settlement.id
        assert refund.amount == Decimal("100.0")
        assert refund.status == RefundStatus.COMPLETED

    async def test_full_refund_updates_settlement_status(self, engine, funded_wallets):
        """Settlement status should be 'refunded' after full refund."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=50.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id)

        # Check settlement status updated
        settlement_data = await engine.storage.get_settlement(settlement.id)
        assert settlement_data["status"] == "refunded"

    async def test_full_refund_returns_refund_object(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=25.0)
        settlement = await engine.capture(intent.id)
        refund = await engine.refund_settlement(settlement.id)

        assert isinstance(refund, Refund)
        assert refund.id  # has an id
        assert refund.settlement_id == settlement.id


# ---------------------------------------------------------------------------
# Partial refund
# ---------------------------------------------------------------------------


class TestPartialRefund:
    async def test_partial_refund_deducts_correct_amount(self, engine, funded_wallets):
        """Partial refund should only reverse the specified amount."""
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        refund = await engine.refund_settlement(settlement.id, amount=Decimal("40.00"))

        assert refund.amount == Decimal("40.00")
        assert await wallet.get_balance("agent-a") == 940.0
        assert await wallet.get_balance("agent-b") == 560.0

    async def test_partial_refund_updates_settlement_status(self, engine, funded_wallets):
        """Settlement status should be 'partially_refunded' after partial refund."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))

        settlement_data = await engine.storage.get_settlement(settlement.id)
        assert settlement_data["status"] == "partially_refunded"

    async def test_multiple_partial_refunds_up_to_original(self, engine, funded_wallets):
        """Multiple partial refunds should work as long as total <= original amount."""
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        # First partial refund: 30
        await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))
        # Second partial refund: 40
        await engine.refund_settlement(settlement.id, amount=Decimal("40.00"))
        # Third partial refund: 30 (exact remainder)
        await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))

        # All funds returned
        assert await wallet.get_balance("agent-a") == 1000.0
        assert await wallet.get_balance("agent-b") == 500.0

        # Settlement should now be "refunded" (fully)
        settlement_data = await engine.storage.get_settlement(settlement.id)
        assert settlement_data["status"] == "refunded"

    async def test_refund_then_full_remaining(self, engine, funded_wallets):
        """Partial then full-remaining refund should work."""
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        # Partial refund first
        await engine.refund_settlement(settlement.id, amount=Decimal("60.00"))

        # Full refund of remaining (no amount means "refund the rest")
        refund = await engine.refund_settlement(settlement.id)
        assert refund.amount == Decimal("40.0")

        assert await wallet.get_balance("agent-a") == 1000.0
        assert await wallet.get_balance("agent-b") == 500.0


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestRefundErrors:
    async def test_refund_exceeding_remaining_raises_error(self, engine, funded_wallets):
        """Refund amount > remaining should raise PaymentError."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        with pytest.raises(PaymentError, match="exceeds"):
            await engine.refund_settlement(settlement.id, amount=Decimal("150.00"))

    async def test_refund_exceeding_after_partial(self, engine, funded_wallets):
        """After partial refund, requesting more than remaining should fail."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id, amount=Decimal("80.00"))

        with pytest.raises(PaymentError, match="exceeds"):
            await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))

    async def test_refund_nonexistent_settlement(self, engine, funded_wallets):
        """Refunding a non-existent settlement should raise SettlementNotFoundError."""
        with pytest.raises(SettlementNotFoundError):
            await engine.refund_settlement("nonexistent-settlement-id")

    async def test_refund_already_fully_refunded(self, engine, funded_wallets):
        """Double full refund should raise InvalidStateError."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=50.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id)

        with pytest.raises(InvalidStateError, match="refunded"):
            await engine.refund_settlement(settlement.id)

    async def test_refund_zero_amount_raises_error(self, engine, funded_wallets):
        """Refund with amount=0 should raise PaymentError."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=50.0)
        settlement = await engine.capture(intent.id)

        with pytest.raises(PaymentError, match="positive"):
            await engine.refund_settlement(settlement.id, amount=Decimal("0"))

    async def test_refund_negative_amount_raises_error(self, engine, funded_wallets):
        """Refund with negative amount should raise PaymentError."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=50.0)
        settlement = await engine.capture(intent.id)

        with pytest.raises(PaymentError, match="positive"):
            await engine.refund_settlement(settlement.id, amount=Decimal("-10"))


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


class TestDecimalPrecision:
    async def test_decimal_precision_maintained(self, engine, funded_wallets):
        """Refund should maintain Decimal precision, not use float."""
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=33.33)
        settlement = await engine.capture(intent.id)

        refund = await engine.refund_settlement(settlement.id, amount=Decimal("11.11"))
        assert refund.amount == Decimal("11.11")


# ---------------------------------------------------------------------------
# Storage: refund tracking
# ---------------------------------------------------------------------------


class TestRefundStorage:
    async def test_get_refunds_for_settlement(self, engine, funded_wallets):
        """Should return all refunds for a given settlement."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))
        await engine.refund_settlement(settlement.id, amount=Decimal("20.00"))

        refunds = await engine.storage.get_refunds_for_settlement(settlement.id)
        assert len(refunds) == 2
        amounts = {r["amount"] for r in refunds}
        # amounts are stored/retrieved as float due to atomic conversion
        assert 30.0 in amounts
        assert 20.0 in amounts

    async def test_get_total_refunded(self, engine, funded_wallets):
        """Should return sum of all refunded amounts for a settlement."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(settlement.id, amount=Decimal("30.00"))
        await engine.refund_settlement(settlement.id, amount=Decimal("25.00"))

        total = await engine.storage.get_total_refunded(settlement.id)
        assert total == Decimal("55.0")

    async def test_get_total_refunded_no_refunds(self, engine, funded_wallets):
        """Should return 0 for a settlement with no refunds."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)

        total = await engine.storage.get_total_refunded(settlement.id)
        assert total == Decimal("0")

    async def test_refund_reason_stored(self, engine, funded_wallets):
        """Refund reason should be persisted and retrievable."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=100.0)
        settlement = await engine.capture(intent.id)
        await engine.refund_settlement(
            settlement.id,
            amount=Decimal("50.00"),
            reason="Service not delivered",
        )

        refunds = await engine.storage.get_refunds_for_settlement(settlement.id)
        assert len(refunds) == 1
        assert refunds[0]["reason"] == "Service not delivered"
