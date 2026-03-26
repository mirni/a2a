"""Tests for tool handler business logic."""

import pytest

from src.client import StripeClient
from src.errors import ValidationError
from src.models import (
    CreateCustomerInput,
    CreatePaymentIntentInput,
    CreateRefundInput,
    CreateSubscriptionInput,
    ListChargesInput,
    ListInvoicesInput,
)
from src.tools import (
    create_customer,
    create_payment_intent,
    create_refund,
    create_subscription,
    get_balance,
    list_charges,
    list_invoices,
)

from .conftest import MockTransport, make_error_response, make_stripe_response


class TestCreateCustomer:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"id": "cus_new", "object": "customer", "email": "a@b.com"})
        )
        input_model = CreateCustomerInput(email="a@b.com", idempotency_key="k1")
        result = await create_customer(stripe_client, input_model)
        assert result.success is True
        assert result.data["id"] == "cus_new"

    async def test_with_metadata(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"id": "cus_meta", "object": "customer"})
        )
        input_model = CreateCustomerInput(
            email="a@b.com",
            name="Alice",
            metadata={"plan": "pro"},
            idempotency_key="k2",
        )
        result = await create_customer(stripe_client, input_model)
        assert result.success is True

    async def test_api_error_returns_error_result(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(400, message="Email invalid"))
        input_model = CreateCustomerInput(email="bad", idempotency_key="k3")
        result = await create_customer(stripe_client, input_model)
        assert result.success is False
        assert result.error["code"] == "UPSTREAM_ERROR"


class TestCreatePaymentIntent:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "id": "pi_1",
                "object": "payment_intent",
                "amount": 5000,
                "currency": "usd",
                "status": "requires_payment_method",
            })
        )
        input_model = CreatePaymentIntentInput(
            amount=5000, currency="usd", idempotency_key="pi-k1"
        )
        result = await create_payment_intent(stripe_client, input_model)
        assert result.success is True
        assert result.data["amount"] == 5000

    async def test_with_customer(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"id": "pi_2", "object": "payment_intent"})
        )
        input_model = CreatePaymentIntentInput(
            amount=1000,
            currency="eur",
            customer_id="cus_1",
            description="Test payment",
            idempotency_key="pi-k2",
        )
        result = await create_payment_intent(stripe_client, input_model)
        assert result.success is True


class TestListCharges:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "object": "list",
                "data": [{"id": "ch_1"}, {"id": "ch_2"}],
                "has_more": False,
            })
        )
        input_model = ListChargesInput(limit=10)
        result = await list_charges(stripe_client, input_model)
        assert result.success is True
        assert len(result.data["data"]) == 2

    async def test_with_filters(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [], "has_more": False})
        )
        input_model = ListChargesInput(
            limit=5, customer="cus_1", created_gte=1000000
        )
        result = await list_charges(stripe_client, input_model)
        assert result.success is True

    async def test_pagination(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "object": "list",
                "data": [{"id": "ch_3"}],
                "has_more": True,
            })
        )
        input_model = ListChargesInput(limit=1, starting_after="ch_2")
        result = await list_charges(stripe_client, input_model)
        assert result.success is True
        assert result.data["has_more"] is True


class TestCreateSubscription:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "id": "sub_1",
                "object": "subscription",
                "status": "active",
            })
        )
        input_model = CreateSubscriptionInput(
            customer_id="cus_1",
            price_id="price_1",
            idempotency_key="sub-k1",
        )
        result = await create_subscription(stripe_client, input_model)
        assert result.success is True
        assert result.data["status"] == "active"

    async def test_with_trial(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"id": "sub_2", "object": "subscription", "status": "trialing"})
        )
        input_model = CreateSubscriptionInput(
            customer_id="cus_1",
            price_id="price_1",
            trial_period_days=14,
            idempotency_key="sub-k2",
        )
        result = await create_subscription(stripe_client, input_model)
        assert result.success is True


class TestGetBalance:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "object": "balance",
                "available": [{"amount": 1000, "currency": "usd"}],
                "pending": [{"amount": 500, "currency": "usd"}],
            })
        )
        result = await get_balance(stripe_client)
        assert result.success is True
        assert result.data["available"][0]["amount"] == 1000

    async def test_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(401, message="Invalid API Key"))
        result = await get_balance(stripe_client)
        assert result.success is False
        assert result.error["code"] == "AUTH_ERROR"


class TestCreateRefund:
    async def test_success_with_payment_intent(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "id": "re_1",
                "object": "refund",
                "amount": 5000,
                "status": "succeeded",
            })
        )
        input_model = CreateRefundInput(
            payment_intent_id="pi_1", idempotency_key="ref-k1"
        )
        result = await create_refund(stripe_client, input_model)
        assert result.success is True
        assert result.data["status"] == "succeeded"

    async def test_success_with_charge(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"id": "re_2", "object": "refund"})
        )
        input_model = CreateRefundInput(
            charge_id="ch_1", amount=500, reason="duplicate", idempotency_key="ref-k2"
        )
        result = await create_refund(stripe_client, input_model)
        assert result.success is True

    async def test_missing_both_ids_raises(self, stripe_client):
        input_model = CreateRefundInput(idempotency_key="ref-k3")
        with pytest.raises(ValidationError) as exc_info:
            await create_refund(stripe_client, input_model)
        assert exc_info.value.code == "VALIDATION_ERROR"


class TestListInvoices:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "object": "list",
                "data": [{"id": "in_1", "status": "paid"}],
                "has_more": False,
            })
        )
        input_model = ListInvoicesInput()
        result = await list_invoices(stripe_client, input_model)
        assert result.success is True
        assert result.data["data"][0]["status"] == "paid"

    async def test_with_all_filters(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [], "has_more": False})
        )
        input_model = ListInvoicesInput(
            limit=20,
            customer="cus_1",
            status="open",
            created_gte=1000,
            created_lte=2000,
            starting_after="in_0",
        )
        result = await list_invoices(stripe_client, input_model)
        assert result.success is True
