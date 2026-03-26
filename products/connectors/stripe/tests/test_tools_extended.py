"""Extended tests for tool handlers — covers optional parameter branches and error paths."""

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


class TestCreateCustomerBranches:
    async def test_with_description(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "cus_d"}))
        inp = CreateCustomerInput(
            email="a@b.com", description="A VIP", idempotency_key="k-desc"
        )
        result = await create_customer(stripe_client, inp)
        assert result.success is True

    async def test_with_all_optional_fields(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "cus_full"}))
        inp = CreateCustomerInput(
            email="a@b.com",
            name="Bob",
            description="VIP customer",
            metadata={"tier": "gold"},
            idempotency_key="k-full",
        )
        result = await create_customer(stripe_client, inp)
        assert result.success is True


class TestCreatePaymentIntentBranches:
    async def test_with_all_optional(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "pi_full"}))
        inp = CreatePaymentIntentInput(
            amount=1500,
            currency="eur",
            customer_id="cus_1",
            description="Monthly fee",
            metadata={"order": "123"},
            idempotency_key="pi-full",
        )
        result = await create_payment_intent(stripe_client, inp)
        assert result.success is True

    async def test_api_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(400, message="Invalid currency"))
        inp = CreatePaymentIntentInput(
            amount=100, currency="usd", idempotency_key="pi-err"
        )
        result = await create_payment_intent(stripe_client, inp)
        assert result.success is False
        assert result.error["code"] == "UPSTREAM_ERROR"


class TestListChargesBranches:
    async def test_api_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(401, message="Bad key"))
        inp = ListChargesInput()
        result = await list_charges(stripe_client, inp)
        assert result.success is False


class TestCreateSubscriptionBranches:
    async def test_with_metadata_and_trial(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "sub_full"}))
        inp = CreateSubscriptionInput(
            customer_id="cus_1",
            price_id="price_1",
            quantity=2,
            trial_period_days=7,
            metadata={"plan": "enterprise"},
            idempotency_key="sub-full",
        )
        result = await create_subscription(stripe_client, inp)
        assert result.success is True

    async def test_api_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(400, message="No such customer"))
        inp = CreateSubscriptionInput(
            customer_id="cus_bad", price_id="price_1", idempotency_key="sub-err"
        )
        result = await create_subscription(stripe_client, inp)
        assert result.success is False


class TestCreateRefundBranches:
    async def test_with_all_optional(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "re_full"}))
        inp = CreateRefundInput(
            payment_intent_id="pi_1",
            amount=200,
            reason="duplicate",
            metadata={"note": "test"},
            idempotency_key="ref-full",
        )
        result = await create_refund(stripe_client, inp)
        assert result.success is True

    async def test_api_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(400, message="Already refunded"))
        inp = CreateRefundInput(
            charge_id="ch_1", idempotency_key="ref-err"
        )
        result = await create_refund(stripe_client, inp)
        assert result.success is False


class TestListInvoicesBranches:
    async def test_api_error(self, stripe_client, mock_transport):
        mock_transport.add_response(make_error_response(500, message="Server error"))
        inp = ListInvoicesInput()
        result = await list_invoices(stripe_client, inp)
        assert result.success is False
