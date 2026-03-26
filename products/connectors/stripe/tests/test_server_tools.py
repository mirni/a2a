"""Tests for MCP server tool wrapper functions.

These tests mock the MCP context to exercise the server-level tool wrappers
including Pydantic validation and context extraction.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.client import StripeClient
from src.server import (
    create_customer_tool,
    create_payment_intent_tool,
    create_refund_tool,
    create_subscription_tool,
    get_balance_tool,
    list_charges_tool,
    list_invoices_tool,
    mcp,
)

from .conftest import MockTransport, make_error_response, make_stripe_response


def _make_mock_context(stripe_client: StripeClient) -> MagicMock:
    """Build a mock MCP context with a StripeClient."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"stripe_client": stripe_client}
    return ctx


class TestCreateCustomerTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "cus_1", "object": "customer"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_customer_tool(email="a@b.com", idempotency_key="k1")
        result = json.loads(raw)
        assert result["success"] is True
        assert result["data"]["id"] == "cus_1"

    async def test_with_all_params(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "cus_2"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_customer_tool(
                email="a@b.com",
                idempotency_key="k2",
                name="Alice",
                description="VIP",
                metadata={"tier": "gold"},
            )
        result = json.loads(raw)
        assert result["success"] is True


class TestCreatePaymentIntentTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "pi_1", "amount": 5000}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_payment_intent_tool(
                amount=5000, currency="usd", idempotency_key="pk1"
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_validation_error_bad_currency(self, stripe_client):
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_payment_intent_tool(
                amount=100, currency="x", idempotency_key="pk-bad"
            )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    async def test_with_all_params(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "pi_2"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_payment_intent_tool(
                amount=2000,
                currency="eur",
                idempotency_key="pk2",
                customer_id="cus_1",
                description="Order",
                metadata={"ref": "abc"},
            )
        result = json.loads(raw)
        assert result["success"] is True


class TestListChargesTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [{"id": "ch_1"}], "has_more": False})
        )
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_charges_tool()
        result = json.loads(raw)
        assert result["success"] is True

    async def test_with_filters(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [], "has_more": False})
        )
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_charges_tool(
                limit=5, customer="cus_1", created_gte=1000, created_lte=2000,
                starting_after="ch_0",
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_validation_error_limit(self, stripe_client):
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_charges_tool(limit=200)
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestCreateSubscriptionTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "sub_1", "status": "active"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_subscription_tool(
                customer_id="cus_1", price_id="price_1", idempotency_key="sk1"
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_with_all_params(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "sub_2"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_subscription_tool(
                customer_id="cus_1",
                price_id="price_1",
                idempotency_key="sk2",
                quantity=3,
                trial_period_days=14,
                metadata={"plan": "pro"},
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_validation_error(self, stripe_client):
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_subscription_tool(
                customer_id="cus_1", price_id="price_1", idempotency_key="sk3",
                quantity=0,  # Invalid: must be >= 1
            )
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestGetBalanceTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({
                "object": "balance",
                "available": [{"amount": 1000, "currency": "usd"}],
            })
        )
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await get_balance_tool()
        result = json.loads(raw)
        assert result["success"] is True
        assert result["data"]["available"][0]["amount"] == 1000


class TestCreateRefundTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "re_1", "status": "succeeded"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_refund_tool(
                idempotency_key="rk1", payment_intent_id="pi_1"
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_validation_error_missing_ids(self, stripe_client):
        """Neither payment_intent_id nor charge_id provided."""
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_refund_tool(idempotency_key="rk2")
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"

    async def test_with_all_params(self, stripe_client, mock_transport):
        mock_transport.add_response(make_stripe_response({"id": "re_2"}))
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await create_refund_tool(
                idempotency_key="rk3",
                charge_id="ch_1",
                amount=500,
                reason="requested_by_customer",
                metadata={"note": "test"},
            )
        result = json.loads(raw)
        assert result["success"] is True


class TestListInvoicesTool:
    async def test_success(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [{"id": "in_1"}], "has_more": False})
        )
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_invoices_tool()
        result = json.loads(raw)
        assert result["success"] is True

    async def test_with_all_filters(self, stripe_client, mock_transport):
        mock_transport.add_response(
            make_stripe_response({"object": "list", "data": [], "has_more": False})
        )
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_invoices_tool(
                limit=20,
                starting_after="in_0",
                customer="cus_1",
                status="paid",
                created_gte=1000,
                created_lte=2000,
            )
        result = json.loads(raw)
        assert result["success"] is True

    async def test_validation_error(self, stripe_client):
        mock_ctx = _make_mock_context(stripe_client)
        with patch.object(mcp, "get_context", return_value=mock_ctx):
            raw = await list_invoices_tool(limit=0)  # Invalid: must be >= 1
        result = json.loads(raw)
        assert result["success"] is False
        assert result["error"]["code"] == "VALIDATION_ERROR"


class TestServerLifespan:
    async def test_lifespan_creates_and_closes_client(self):
        """Test the lifespan context manager."""
        from src.server import lifespan

        mock_server = MagicMock()
        async with lifespan(mock_server) as ctx:
            assert "stripe_client" in ctx
            assert isinstance(ctx["stripe_client"], StripeClient)
            client = ctx["stripe_client"]
        # After exit, client should have been closed (no error on exit)
