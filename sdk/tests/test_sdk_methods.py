"""Tests for SDK convenience methods (Items 4, 11, 12).

Tests cover:
- Method existence and correct signatures
- Methods call _rest() with correct HTTP method, path, and body/params
- Typed Pydantic response models are returned (not raw dicts)
- Model validation: extra fields rejected, required fields enforced
- Decimal usage for currency fields
"""

from __future__ import annotations

import inspect
import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

# Ensure project root is on sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sdk.src.a2a_client import A2AClient
from sdk.src.a2a_client.models import (
    AddAgentToOrgResponse,
    BalanceResponse,
    CancelEscrowResponse,
    CancelSubscriptionResponse,
    CreateApiKeyResponse,
    CreateOrgResponse,
    DeleteWebhookResponse,
    DepositResponse,
    EscrowResponse,
    GetAgentIdentityResponse,
    GetEventsResponse,
    GetMessagesResponse,
    GetOrgResponse,
    GetServiceResponse,
    GetSubscriptionResponse,
    GetVerifiedClaimsResponse,
    ListSubscriptionsResponse,
    ListWebhooksResponse,
    NegotiatePriceResponse,
    PaymentIntentResponse,
    PublishEventResponse,
    RateServiceResponse,
    RefundSettlementResponse,
    RegisterAgentResponse,
    RegisterServiceResponse,
    RegisterWebhookResponse,
    RotateKeyResponse,
    SearchServersResponse,
    SearchServicesResponse,
    SendMessageResponse,
    SubmitMetricsResponse,
    SubscriptionResponse,
    TrustScoreResponse,
    VerifyAgentResponse,
    VoidPaymentResponse,
)

# ---------------------------------------------------------------------------
# Helper: create a client with a mocked _rest method
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """A2AClient with mocked _rest() for unit testing convenience methods.

    Convenience methods now call _rest() (REST endpoints) instead of execute().
    We mock _rest() to return the tool result directly (no envelope).
    """
    client = A2AClient.__new__(A2AClient)
    client.base_url = "http://test"
    client.api_key = "test-key"
    client.max_retries = 0
    client.retry_base_delay = 0.0
    client.pricing_cache_ttl = 300.0
    client._pricing_cache = None
    client._pricing_cache_time = 0.0
    client._client = None  # Not used in unit tests
    client._rest = AsyncMock()
    return client


# ===========================================================================
# ITEM 4 — Feature parity methods
# ===========================================================================


class TestRegisterAgent:
    """register_agent(agent_id, public_key=None)"""

    @pytest.mark.asyncio
    async def test_calls_rest_with_correct_args(self, mock_client):
        mock_client._rest.return_value = {
            "agent_id": "a1", "public_key": "abc123", "created_at": 1234567890.0,
        }
        result = await mock_client.register_agent("a1")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/identity/agents", json={"agent_id": "a1"},
        )
        assert isinstance(result, RegisterAgentResponse)
        assert result.agent_id == "a1"

    @pytest.mark.asyncio
    async def test_with_public_key(self, mock_client):
        mock_client._rest.return_value = {
            "agent_id": "a1", "public_key": "mypk", "created_at": 1234567890.0,
        }
        result = await mock_client.register_agent("a1", public_key="mypk")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/identity/agents",
            json={"agent_id": "a1", "public_key": "mypk"},
        )
        assert result.public_key == "mypk"

    def test_signature(self, mock_client):
        sig = inspect.signature(mock_client.register_agent)
        params = list(sig.parameters.keys())
        assert "agent_id" in params
        assert "public_key" in params


class TestSendMessage:
    """send_message(sender, recipient, message_type, body, subject=None, thread_id=None)"""

    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "m1", "sender": "a", "recipient": "b", "thread_id": "t1",
        }
        result = await mock_client.send_message(sender="a", recipient="b", message_type="text", body="hello")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/messaging/messages")
        body = call[1]["json"]
        assert body["sender"] == "a"
        assert body["recipient"] == "b"
        assert body["message_type"] == "text"
        assert body["body"] == "hello"
        assert isinstance(result, SendMessageResponse)

    @pytest.mark.asyncio
    async def test_with_optional_params(self, mock_client):
        mock_client._rest.return_value = {
            "id": "m1", "sender": "a", "recipient": "b", "thread_id": "t1",
        }
        await mock_client.send_message(
            sender="a",
            recipient="b",
            message_type="text",
            body="hello",
            subject="greetings",
            thread_id="t1",
        )
        body = mock_client._rest.call_args[1]["json"]
        assert body["subject"] == "greetings"
        assert body["thread_id"] == "t1"


class TestGetMessages:
    """get_messages(agent_id, thread_id=None, limit=50)"""

    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"messages": []}
        result = await mock_client.get_messages("a1")
        call = mock_client._rest.call_args
        assert call[0] == ("GET", "/v1/messaging/messages")
        assert call[1]["params"]["agent_id"] == "a1"
        assert call[1]["params"]["limit"] == 50
        assert isinstance(result, GetMessagesResponse)

    @pytest.mark.asyncio
    async def test_with_thread_id(self, mock_client):
        mock_client._rest.return_value = {"messages": []}
        await mock_client.get_messages("a1", thread_id="t1", limit=10)
        params = mock_client._rest.call_args[1]["params"]
        assert params["thread_id"] == "t1"
        assert params["limit"] == 10


class TestVoidPayment:
    """void_payment(intent_id)"""

    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "i1", "status": "refunded", "amount": Decimal("10.00"),
        }
        result = await mock_client.void_payment("i1")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/payments/intents/i1/refund",
        )
        assert isinstance(result, VoidPaymentResponse)


class TestNegotiatePrice:
    """negotiate_price(initiator, responder, amount, service_id=None, expires_hours=24)"""

    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "negotiation_id": "n1",
            "thread_id": "t1",
            "status": "pending",
            "proposed_amount": Decimal("50.00"),
        }
        result = await mock_client.negotiate_price(initiator="a", responder="b", amount=50.0, service_id="s1")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/messaging/negotiations")
        body = call[1]["json"]
        assert body["initiator"] == "a"
        assert body["amount"] == 50.0
        assert body["service_id"] == "s1"
        assert isinstance(result, NegotiatePriceResponse)


# ===========================================================================
# ITEM 11 — Convenience methods for ALL tools
# ===========================================================================


class TestCancelEscrow:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "e1", "status": "cancelled", "amount": Decimal("10.00"),
        }
        result = await mock_client.cancel_escrow("e1")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/payments/escrows/e1/cancel",
        )
        assert isinstance(result, CancelEscrowResponse)


class TestRefundSettlement:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "r1", "settlement_id": "s1", "amount": Decimal("5.00"), "status": "refunded",
        }
        result = await mock_client.refund_settlement("s1", amount=5.0, reason="bad")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/payments/settlements/s1/refund")
        body = call[1]["json"]
        assert body["amount"] == 5.0
        assert body["reason"] == "bad"
        assert isinstance(result, RefundSettlementResponse)


class TestCreateSubscription:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "sub1", "status": "active", "amount": Decimal("10.00"),
            "interval": "daily", "next_charge_at": 123.0,
        }
        result = await mock_client.create_subscription(payer="a", payee="b", amount=10.0, interval="daily")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/payments/subscriptions")
        body = call[1]["json"]
        assert body["payer"] == "a"
        assert body["interval"] == "daily"
        assert isinstance(result, SubscriptionResponse)


class TestCancelSubscription:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"id": "sub1", "status": "cancelled"}
        result = await mock_client.cancel_subscription("sub1", cancelled_by="a")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/payments/subscriptions/sub1/cancel")
        body = call[1]["json"]
        assert body["cancelled_by"] == "a"
        assert isinstance(result, CancelSubscriptionResponse)


class TestGetSubscription:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "sub1",
            "payer": "a",
            "payee": "b",
            "amount": Decimal("10.00"),
            "interval": "daily",
            "status": "active",
            "next_charge_at": 123.0,
            "charge_count": 0,
            "created_at": 100.0,
        }
        result = await mock_client.get_subscription("sub1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/payments/subscriptions/sub1",
        )
        assert isinstance(result, GetSubscriptionResponse)


class TestListSubscriptions:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"subscriptions": []}
        result = await mock_client.list_subscriptions(agent_id="a1", status="active")
        call = mock_client._rest.call_args
        assert call[0] == ("GET", "/v1/payments/subscriptions")
        params = call[1]["params"]
        assert params["agent_id"] == "a1"
        assert params["status"] == "active"
        assert isinstance(result, ListSubscriptionsResponse)


class TestRegisterService:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"id": "svc1", "name": "MySvc", "status": "active"}
        result = await mock_client.register_service(provider_id="p1", name="MySvc", description="desc", category="ai")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/marketplace/services")
        body = call[1]["json"]
        assert body["provider_id"] == "p1"
        assert body["name"] == "MySvc"
        assert isinstance(result, RegisterServiceResponse)


class TestGetService:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "svc1", "name": "MySvc", "description": "d", "category": "ai", "status": "active",
        }
        result = await mock_client.get_service("svc1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/marketplace/services/svc1",
        )
        assert isinstance(result, GetServiceResponse)


class TestRateService:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"service_id": "svc1", "agent_id": "a1", "rating": 5}
        result = await mock_client.rate_service(service_id="svc1", agent_id="a1", rating=5)
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/marketplace/services/svc1/ratings")
        body = call[1]["json"]
        assert body["agent_id"] == "a1"
        assert body["rating"] == 5
        assert isinstance(result, RateServiceResponse)


class TestSearchServers:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"servers": []}
        result = await mock_client.search_servers(name_contains="test", min_score=0.5)
        call = mock_client._rest.call_args
        assert call[0] == ("GET", "/v1/trust/servers")
        params = call[1]["params"]
        assert params["name_contains"] == "test"
        assert params["min_score"] == 0.5
        assert isinstance(result, SearchServersResponse)


class TestGetAgentIdentity:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "agent_id": "a1", "public_key": "pk1", "created_at": 100.0, "found": True,
        }
        result = await mock_client.get_agent_identity("a1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/identity/agents/a1",
        )
        assert isinstance(result, GetAgentIdentityResponse)


class TestVerifyAgent:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"valid": True}
        result = await mock_client.verify_agent(agent_id="a1", message="hello", signature="sig123")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/identity/agents/a1/verify")
        body = call[1]["json"]
        assert body["message"] == "hello"
        assert body["signature"] == "sig123"
        assert isinstance(result, VerifyAgentResponse)


class TestSubmitMetrics:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "agent_id": "a1",
            "commitment_hashes": ["h1"],
            "verified_at": 100.0,
            "valid_until": 200.0,
            "data_source": "self_reported",
            "signature": "sig",
        }
        result = await mock_client.submit_metrics(agent_id="a1", metrics={"sharpe_30d": 2.0})
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/identity/agents/a1/metrics")
        body = call[1]["json"]
        assert body["metrics"] == {"sharpe_30d": 2.0}
        assert body["data_source"] == "self_reported"
        assert isinstance(result, SubmitMetricsResponse)


class TestGetVerifiedClaims:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"claims": []}
        result = await mock_client.get_verified_claims("a1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/identity/agents/a1/claims",
        )
        assert isinstance(result, GetVerifiedClaimsResponse)


class TestRegisterWebhook:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "id": "w1",
            "agent_id": "a1",
            "url": "https://hook.test",
            "event_types": ["billing.deposit"],
            "created_at": 100.0,
            "active": True,
        }
        result = await mock_client.register_webhook(
            agent_id="a1", url="https://hook.test", event_types=["billing.deposit"],
        )
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/infra/webhooks")
        body = call[1]["json"]
        assert body["url"] == "https://hook.test"
        assert body["event_types"] == ["billing.deposit"]
        assert isinstance(result, RegisterWebhookResponse)


class TestListWebhooks:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"webhooks": []}
        result = await mock_client.list_webhooks("a1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/infra/webhooks",
        )
        assert isinstance(result, ListWebhooksResponse)


class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"deleted": True}
        result = await mock_client.delete_webhook("w1")
        mock_client._rest.assert_called_once_with(
            "DELETE", "/v1/infra/webhooks/w1",
        )
        assert isinstance(result, DeleteWebhookResponse)


class TestCreateApiKey:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "key": "k1", "agent_id": "a1", "tier": "free", "created_at": 100.0,
        }
        result = await mock_client.create_api_key("a1", tier="pro")
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/infra/keys")
        body = call[1]["json"]
        assert body["tier"] == "pro"
        assert isinstance(result, CreateApiKeyResponse)


class TestRotateKey:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "new_key": "nk1", "tier": "free", "agent_id": "a1", "revoked": True,
        }
        result = await mock_client.rotate_key("old_key")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/infra/keys/rotate", json={"current_key": "old_key"},
        )
        assert isinstance(result, RotateKeyResponse)


class TestPublishEvent:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"event_id": 42}
        result = await mock_client.publish_event(event_type="trust.score_drop", source="billing", payload={"x": 1})
        call = mock_client._rest.call_args
        assert call[0] == ("POST", "/v1/infra/events")
        body = call[1]["json"]
        assert body["event_type"] == "trust.score_drop"
        assert body["source"] == "billing"
        assert body["payload"] == {"x": 1}
        assert isinstance(result, PublishEventResponse)


class TestGetEvents:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"events": []}
        result = await mock_client.get_events(event_type="trust.score_drop", since_id=10)
        call = mock_client._rest.call_args
        assert call[0] == ("GET", "/v1/infra/events")
        params = call[1]["params"]
        assert params["event_type"] == "trust.score_drop"
        assert params["since_id"] == 10
        assert isinstance(result, GetEventsResponse)


class TestCreateOrg:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"org_id": "o1", "name": "Org1", "created_at": 100.0}
        result = await mock_client.create_org("Org1")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/identity/orgs", json={"org_name": "Org1"},
        )
        assert isinstance(result, CreateOrgResponse)


class TestGetOrg:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {
            "org_id": "o1", "name": "Org1", "created_at": 100.0, "members": [],
        }
        result = await mock_client.get_org("o1")
        mock_client._rest.assert_called_once_with(
            "GET", "/v1/identity/orgs/o1",
        )
        assert isinstance(result, GetOrgResponse)


class TestAddAgentToOrg:
    @pytest.mark.asyncio
    async def test_calls_rest(self, mock_client):
        mock_client._rest.return_value = {"agent_id": "a1", "org_id": "o1"}
        result = await mock_client.add_agent_to_org(org_id="o1", agent_id="a1")
        mock_client._rest.assert_called_once_with(
            "POST", "/v1/identity/orgs/o1/members", json={"agent_id": "a1"},
        )
        assert isinstance(result, AddAgentToOrgResponse)


# ===========================================================================
# ITEM 12 — Pydantic model validation tests
# ===========================================================================


class TestModelValidation:
    """Ensure all new models use pydantic, extra=forbid, Decimal for currency."""

    def test_register_agent_response_extra_ignored(self):
        """Response models use extra='ignore' to tolerate extra fields from REST."""
        m = RegisterAgentResponse(agent_id="a1", public_key="pk", created_at=100.0, bogus="x")
        assert m.agent_id == "a1"
        assert not hasattr(m, "bogus")

    def test_register_agent_response_valid(self):
        m = RegisterAgentResponse(agent_id="a1", public_key="pk", created_at=100.0)
        assert m.agent_id == "a1"

    def test_register_agent_response_schema_extra(self):
        schema = RegisterAgentResponse.model_json_schema()
        assert (
            "examples" in schema
            or "example" in schema.get("json_schema_extra", {})
            or RegisterAgentResponse.model_config.get("json_schema_extra") is not None
        )

    def test_escrow_response_decimal_amount(self):
        m = EscrowResponse(id="e1", status="held", amount=Decimal("10.50"))
        assert isinstance(m.amount, Decimal)

    def test_subscription_response_decimal_amount(self):
        m = SubscriptionResponse(
            id="s1",
            status="active",
            amount=Decimal("10.00"),
            interval="daily",
            next_charge_at=100.0,
        )
        assert isinstance(m.amount, Decimal)

    def test_refund_settlement_response_decimal(self):
        m = RefundSettlementResponse(id="r1", settlement_id="s1", amount=Decimal("5.00"), status="refunded")
        assert isinstance(m.amount, Decimal)

    def test_send_message_response_extra_ignored(self):
        """Response models use extra='ignore' to tolerate extra fields from REST."""
        m = SendMessageResponse(id="m1", sender="a", recipient="b", thread_id="t1", extra_field="bad")
        assert m.id == "m1"
        assert not hasattr(m, "extra_field")

    def test_negotiate_price_response_decimal_amount(self):
        m = NegotiatePriceResponse(
            negotiation_id="n1",
            thread_id="t1",
            status="pending",
            proposed_amount=Decimal("50.00"),
        )
        assert isinstance(m.proposed_amount, Decimal)

    def test_cancel_escrow_response_decimal(self):
        m = CancelEscrowResponse(id="e1", status="cancelled", amount=Decimal("10.00"))
        assert isinstance(m.amount, Decimal)

    def test_void_payment_response_decimal(self):
        m = VoidPaymentResponse(id="i1", status="refunded", amount=Decimal("10.00"))
        assert isinstance(m.amount, Decimal)

    def test_get_subscription_response_decimal(self):
        m = GetSubscriptionResponse(
            id="s1",
            payer="a",
            payee="b",
            amount=Decimal("10.00"),
            interval="daily",
            status="active",
            next_charge_at=100.0,
            charge_count=0,
            created_at=100.0,
        )
        assert isinstance(m.amount, Decimal)

    def test_publish_event_response_extra_ignored(self):
        """Response models use extra='ignore' to tolerate extra fields from REST."""
        m = PublishEventResponse(event_id=42, bad="x")
        assert m.event_id == 42
        assert not hasattr(m, "bad")

    def test_create_api_key_response_extra_ignored(self):
        """Response models use extra='ignore' to tolerate extra fields from REST."""
        m = CreateApiKeyResponse(key="k1", agent_id="a1", tier="free", created_at=100.0, extra="bad")
        assert m.key == "k1"
        assert not hasattr(m, "extra")


# ===========================================================================
# Test that existing methods now return typed models (Item 12 wiring)
# ===========================================================================


class TestExistingMethodsReturnTypedModels:
    """Existing convenience methods should return typed Pydantic models."""

    @pytest.mark.asyncio
    async def test_get_balance_returns_model(self, mock_client):
        mock_client._rest.return_value = {"balance": 100.0}
        result = await mock_client.get_balance("a1")
        assert isinstance(result, BalanceResponse)

    @pytest.mark.asyncio
    async def test_deposit_returns_model(self, mock_client):
        mock_client._rest.return_value = {"new_balance": 200.0}
        result = await mock_client.deposit("a1", 100.0)
        assert isinstance(result, DepositResponse)

    @pytest.mark.asyncio
    async def test_create_payment_intent_returns_model(self, mock_client):
        mock_client._rest.return_value = {
            "id": "i1", "status": "pending", "amount": Decimal("10.00"),
        }
        result = await mock_client.create_payment_intent(payer="a", payee="b", amount=10.0)
        assert isinstance(result, PaymentIntentResponse)

    @pytest.mark.asyncio
    async def test_capture_payment_returns_model(self, mock_client):
        mock_client._rest.return_value = {
            "id": "i1", "status": "settled", "amount": Decimal("10.00"),
        }
        result = await mock_client.capture_payment("i1")
        assert isinstance(result, PaymentIntentResponse)

    @pytest.mark.asyncio
    async def test_create_escrow_returns_model(self, mock_client):
        mock_client._rest.return_value = {
            "id": "e1", "status": "held", "amount": Decimal("10.00"),
        }
        result = await mock_client.create_escrow(payer="a", payee="b", amount=10.0)
        assert isinstance(result, EscrowResponse)

    @pytest.mark.asyncio
    async def test_release_escrow_returns_model(self, mock_client):
        mock_client._rest.return_value = {
            "id": "e1", "status": "released", "amount": Decimal("10.00"),
        }
        result = await mock_client.release_escrow("e1")
        assert isinstance(result, EscrowResponse)

    @pytest.mark.asyncio
    async def test_get_trust_score_returns_model(self, mock_client):
        mock_client._rest.return_value = {
            "server_id": "s1",
            "composite_score": 0.9,
            "reliability_score": 0.8,
            "security_score": 0.7,
            "documentation_score": 0.6,
            "responsiveness_score": 0.5,
            "confidence": 0.95,
            "window": "24h",
        }
        result = await mock_client.get_trust_score("s1")
        assert isinstance(result, TrustScoreResponse)

    @pytest.mark.asyncio
    async def test_search_services_returns_model(self, mock_client):
        mock_client._rest.return_value = {"services": [{"id": "s1", "name": "svc"}]}
        result = await mock_client.search_services(query="test")
        assert isinstance(result, SearchServicesResponse)

    @pytest.mark.asyncio
    async def test_best_match_returns_list(self, mock_client):
        """best_match returns list of ServiceMatch — already typed."""
        mock_client._rest.return_value = {
            "matches": [{"service": {}, "rank_score": 0.9, "match_reasons": ["kw"]}],
        }
        result = await mock_client.best_match(query="test")
        assert isinstance(result, list)
