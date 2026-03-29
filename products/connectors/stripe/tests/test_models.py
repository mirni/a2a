"""Tests for Pydantic input/output models."""

import pytest
from pydantic import ValidationError
from src.models import (
    CreateCustomerInput,
    CreatePaymentIntentInput,
    CreateRefundInput,
    CreateSubscriptionInput,
    ListChargesInput,
    ListInvoicesInput,
    ToolResult,
)


class TestCreateCustomerInput:
    def test_valid_minimal(self):
        m = CreateCustomerInput(email="a@b.com", idempotency_key="key-1")
        assert m.email == "a@b.com"
        assert m.name is None

    def test_valid_full(self):
        m = CreateCustomerInput(
            email="a@b.com",
            name="Alice",
            description="VIP",
            metadata={"tier": "gold"},
            idempotency_key="key-2",
        )
        assert m.metadata == {"tier": "gold"}

    def test_missing_email_fails(self):
        with pytest.raises(ValidationError):
            CreateCustomerInput(idempotency_key="key-3")

    def test_missing_idempotency_key_fails(self):
        with pytest.raises(ValidationError):
            CreateCustomerInput(email="a@b.com")


class TestCreatePaymentIntentInput:
    def test_valid(self):
        m = CreatePaymentIntentInput(amount=5000, currency="usd", idempotency_key="pi-1")
        assert m.amount == 5000
        assert m.currency == "usd"

    def test_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            CreatePaymentIntentInput(amount=0, currency="usd", idempotency_key="pi-2")

    def test_amount_negative_fails(self):
        with pytest.raises(ValidationError):
            CreatePaymentIntentInput(amount=-100, currency="usd", idempotency_key="pi-3")

    def test_currency_too_long(self):
        with pytest.raises(ValidationError):
            CreatePaymentIntentInput(amount=100, currency="usdd", idempotency_key="pi-4")

    def test_currency_too_short(self):
        with pytest.raises(ValidationError):
            CreatePaymentIntentInput(amount=100, currency="us", idempotency_key="pi-5")


class TestListChargesInput:
    def test_defaults(self):
        m = ListChargesInput()
        assert m.limit == 10
        assert m.starting_after is None

    def test_limit_bounds(self):
        with pytest.raises(ValidationError):
            ListChargesInput(limit=0)
        with pytest.raises(ValidationError):
            ListChargesInput(limit=101)

    def test_with_filters(self):
        m = ListChargesInput(customer="cus_123", created_gte=1000, created_lte=2000)
        assert m.customer == "cus_123"


class TestCreateSubscriptionInput:
    def test_valid(self):
        m = CreateSubscriptionInput(customer_id="cus_1", price_id="price_1", idempotency_key="sub-1")
        assert m.quantity == 1

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValidationError):
            CreateSubscriptionInput(customer_id="cus_1", price_id="price_1", quantity=0, idempotency_key="sub-2")


class TestCreateRefundInput:
    def test_valid_with_payment_intent(self):
        m = CreateRefundInput(payment_intent_id="pi_123", idempotency_key="ref-1")
        assert m.charge_id is None

    def test_valid_with_charge(self):
        m = CreateRefundInput(charge_id="ch_123", idempotency_key="ref-2")
        assert m.payment_intent_id is None

    def test_partial_amount(self):
        m = CreateRefundInput(payment_intent_id="pi_123", amount=500, idempotency_key="ref-3")
        assert m.amount == 500

    def test_amount_must_be_positive(self):
        with pytest.raises(ValidationError):
            CreateRefundInput(payment_intent_id="pi_123", amount=0, idempotency_key="ref-4")


class TestListInvoicesInput:
    def test_defaults(self):
        m = ListInvoicesInput()
        assert m.limit == 10
        assert m.status is None

    def test_with_all_filters(self):
        m = ListInvoicesInput(
            limit=25,
            customer="cus_1",
            status="paid",
            created_gte=100,
            created_lte=200,
        )
        assert m.status == "paid"


class TestToolResult:
    def test_success(self):
        r = ToolResult(success=True, data={"id": "cus_1"})
        d = r.model_dump()
        assert d["success"] is True
        assert d["data"]["id"] == "cus_1"

    def test_error(self):
        r = ToolResult(success=False, error={"code": "VALIDATION_ERROR", "message": "bad"})
        d = r.model_dump()
        assert d["success"] is False
        assert d["error"]["code"] == "VALIDATION_ERROR"
