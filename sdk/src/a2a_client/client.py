"""A2A Commerce Python SDK client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .errors import (
    RETRYABLE_STATUS_CODES,
    raise_for_status,
)
from .models import (
    AddAgentToOrgResponse,
    BalanceResponse,
    CancelEscrowResponse,
    CancelSubscriptionResponse,
    CreateApiKeyResponse,
    CreateOrgResponse,
    DeleteWebhookResponse,
    DepositResponse,
    EscrowResponse,
    ExecuteResponse,
    GetAgentIdentityResponse,
    GetEventsResponse,
    GetMessagesResponse,
    GetOrgResponse,
    GetServiceResponse,
    GetSubscriptionResponse,
    GetVerifiedClaimsResponse,
    HealthResponse,
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
    ServiceMatch,
    SubmitMetricsResponse,
    SubscriptionResponse,
    ToolPricing,
    TrustScoreResponse,
    VerifyAgentResponse,
    VoidPaymentResponse,
)


class A2AClient:
    """Async client for the A2A Commerce gateway.

    Features:
    - Automatic retry with exponential backoff for 429/5xx responses
    - Connection pooling via httpx limits
    - Pricing cache with configurable TTL
    - All endpoints use /v1/ prefix

    Usage::

        async with A2AClient("http://localhost:8000", api_key="a2a_free_...") as client:
            health = await client.health()
            balance = await client.get_balance("my-agent")
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        max_connections: int = 100,
        max_keepalive: int = 20,
        pricing_cache_ttl: float = 300.0,
    ) -> None:
        import os

        self.base_url = (base_url or os.environ.get("A2A_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.api_key = api_key or os.environ.get("A2A_API_KEY")
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.pricing_cache_ttl = pricing_cache_ttl
        self._pricing_cache: list[ToolPricing] | None = None
        self._pricing_cache_time: float = 0.0
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive,
            ),
        )

    async def __aenter__(self) -> A2AClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with retry logic for transient failures."""

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    return resp
                # Retryable HTTP status — treat as error for retry
                if attempt == self.max_retries:
                    return resp  # Return the response on last attempt
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
                if attempt == self.max_retries:
                    raise
            else:
                pass

            # Compute delay
            delay = self.retry_base_delay * (2**attempt)

            # Respect Retry-After header for 429
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass

            await asyncio.sleep(delay)

        # Should not reach here, but return last response if we do
        return resp  # type: ignore[possibly-undefined]

    # ----- Core methods -----

    async def health(self) -> HealthResponse:
        """GET /v1/health"""
        resp = await self._request_with_retry("GET", "/v1/health")
        resp.raise_for_status()
        return HealthResponse.from_dict(resp.json())

    async def pricing(self, use_cache: bool = True) -> list[ToolPricing]:
        """GET /v1/pricing — full catalog with optional caching."""
        now = time.time()
        if use_cache and self._pricing_cache is not None and (now - self._pricing_cache_time) < self.pricing_cache_ttl:
            return self._pricing_cache

        resp = await self._request_with_retry("GET", "/v1/pricing")
        resp.raise_for_status()
        data = resp.json()
        tools = data.get("tools", [])
        result = [ToolPricing.from_dict(t) for t in tools]

        self._pricing_cache = result
        self._pricing_cache_time = now
        return result

    async def pricing_tool(self, tool_name: str) -> ToolPricing:
        """GET /v1/pricing/{tool} — single tool."""
        resp = await self._request_with_retry("GET", f"/v1/pricing/{tool_name}")
        if resp.status_code != 200:
            raise_for_status(resp.status_code, resp.json())
        data = resp.json()
        tool_data = data.get("tool", data)
        return ToolPricing.from_dict(tool_data)

    async def execute(self, tool: str, params: dict[str, Any] | None = None) -> ExecuteResponse:
        """POST /v1/execute — run a tool."""
        resp = await self._request_with_retry(
            "POST",
            "/v1/execute",
            json={"tool": tool, "params": params or {}},
            headers=self._headers(),
        )
        body = resp.json()
        if resp.status_code != 200:
            raise_for_status(resp.status_code, body)
        return ExecuteResponse.from_dict(body)

    def invalidate_pricing_cache(self) -> None:
        """Clear the cached pricing data."""
        self._pricing_cache = None
        self._pricing_cache_time = 0.0

    # =====================================================================
    # Convenience methods — Billing
    # =====================================================================

    async def get_balance(self, agent_id: str) -> BalanceResponse:
        """Get wallet balance for an agent."""
        result = await self.execute("get_balance", {"agent_id": agent_id})
        return BalanceResponse.from_dict(result.result)

    async def deposit(self, agent_id: str, amount: float, description: str = "") -> DepositResponse:
        """Deposit credits into a wallet. Returns new balance."""
        result = await self.execute("deposit", {"agent_id": agent_id, "amount": amount, "description": description})
        return DepositResponse.from_dict(result.result)

    async def get_usage_summary(self, agent_id: str, since: float | None = None) -> dict[str, Any]:
        """Get usage summary for an agent."""
        params: dict[str, Any] = {"agent_id": agent_id}
        if since is not None:
            params["since"] = since
        result = await self.execute("get_usage_summary", params)
        return result.result

    # =====================================================================
    # Convenience methods — Payments
    # =====================================================================

    async def create_payment_intent(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        idempotency_key: str | None = None,
    ) -> PaymentIntentResponse:
        """Create a payment intent."""
        params: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "description": description,
        }
        if idempotency_key:
            params["idempotency_key"] = idempotency_key
        result = await self.execute("create_intent", params)
        return PaymentIntentResponse.from_dict(result.result)

    async def capture_payment(self, intent_id: str) -> PaymentIntentResponse:
        """Capture a pending payment intent."""
        result = await self.execute("capture_intent", {"intent_id": intent_id})
        return PaymentIntentResponse.from_dict(result.result)

    async def void_payment(self, intent_id: str) -> VoidPaymentResponse:
        """Void (refund) a payment intent."""
        result = await self.execute("refund_intent", {"intent_id": intent_id})
        return VoidPaymentResponse.from_dict(result.result)

    async def refund_settlement(
        self,
        settlement_id: str,
        amount: float | None = None,
        reason: str | None = None,
    ) -> RefundSettlementResponse:
        """Refund a settled payment (full or partial)."""
        params: dict[str, Any] = {"settlement_id": settlement_id}
        if amount is not None:
            params["amount"] = amount
        if reason is not None:
            params["reason"] = reason
        result = await self.execute("refund_settlement", params)
        return RefundSettlementResponse.from_dict(result.result)

    async def get_payment_history(self, agent_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get payment history for an agent."""
        result = await self.execute(
            "get_payment_history",
            {"agent_id": agent_id, "limit": limit, "offset": offset},
        )
        return result.result["history"]

    # =====================================================================
    # Convenience methods — Escrow
    # =====================================================================

    async def create_escrow(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        timeout_hours: float | None = None,
    ) -> EscrowResponse:
        """Create an escrow."""
        params: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "description": description,
        }
        if timeout_hours is not None:
            params["timeout_hours"] = timeout_hours
        result = await self.execute("create_escrow", params)
        return EscrowResponse.from_dict(result.result)

    async def release_escrow(self, escrow_id: str) -> EscrowResponse:
        """Release an escrow to the payee."""
        result = await self.execute("release_escrow", {"escrow_id": escrow_id})
        return EscrowResponse.from_dict(result.result)

    async def cancel_escrow(self, escrow_id: str) -> CancelEscrowResponse:
        """Cancel a held escrow and refund the payer."""
        result = await self.execute("cancel_escrow", {"escrow_id": escrow_id})
        return CancelEscrowResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Subscriptions
    # =====================================================================

    async def create_subscription(
        self,
        payer: str,
        payee: str,
        amount: float,
        interval: str,
        description: str = "",
    ) -> SubscriptionResponse:
        """Create a recurring payment subscription."""
        params: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "interval": interval,
        }
        if description:
            params["description"] = description
        result = await self.execute("create_subscription", params)
        return SubscriptionResponse.from_dict(result.result)

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancelled_by: str | None = None,
    ) -> CancelSubscriptionResponse:
        """Cancel an active or suspended subscription."""
        params: dict[str, Any] = {"subscription_id": subscription_id}
        if cancelled_by is not None:
            params["cancelled_by"] = cancelled_by
        result = await self.execute("cancel_subscription", params)
        return CancelSubscriptionResponse.from_dict(result.result)

    async def get_subscription(self, subscription_id: str) -> GetSubscriptionResponse:
        """Get details of a subscription by ID."""
        result = await self.execute("get_subscription", {"subscription_id": subscription_id})
        return GetSubscriptionResponse.from_dict(result.result)

    async def list_subscriptions(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ListSubscriptionsResponse:
        """List subscriptions for an agent."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if status is not None:
            params["status"] = status
        result = await self.execute("list_subscriptions", params)
        return ListSubscriptionsResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Marketplace
    # =====================================================================

    async def register_service(
        self,
        provider_id: str,
        name: str,
        description: str,
        category: str,
        tools: list[str] | None = None,
        tags: list[str] | None = None,
        endpoint: str | None = None,
        pricing: dict[str, Any] | None = None,
    ) -> RegisterServiceResponse:
        """Register a new service in the marketplace."""
        params: dict[str, Any] = {
            "provider_id": provider_id,
            "name": name,
            "description": description,
            "category": category,
        }
        if tools is not None:
            params["tools"] = tools
        if tags is not None:
            params["tags"] = tags
        if endpoint is not None:
            params["endpoint"] = endpoint
        if pricing is not None:
            params["pricing"] = pricing
        result = await self.execute("register_service", params)
        return RegisterServiceResponse.from_dict(result.result)

    async def search_services(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        max_cost: float | None = None,
        limit: int = 20,
    ) -> SearchServicesResponse:
        """Search the marketplace."""
        params: dict[str, Any] = {"limit": limit}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        if tags:
            params["tags"] = tags
        if max_cost is not None:
            params["max_cost"] = max_cost
        result = await self.execute("search_services", params)
        return SearchServicesResponse.from_dict(result.result)

    async def best_match(
        self,
        query: str,
        budget: float | None = None,
        min_trust_score: float | None = None,
        prefer: str = "trust",
        limit: int = 5,
    ) -> list[ServiceMatch]:
        """Find best matching services."""
        params: dict[str, Any] = {"query": query, "prefer": prefer, "limit": limit}
        if budget is not None:
            params["budget"] = budget
        if min_trust_score is not None:
            params["min_trust_score"] = min_trust_score
        result = await self.execute("best_match", params)
        return [ServiceMatch.from_dict(m) for m in result.result["matches"]]

    async def get_service(self, service_id: str) -> GetServiceResponse:
        """Get a marketplace service by its ID."""
        result = await self.execute("get_service", {"service_id": service_id})
        return GetServiceResponse.from_dict(result.result)

    async def rate_service(
        self,
        service_id: str,
        agent_id: str,
        rating: int,
        review: str | None = None,
    ) -> RateServiceResponse:
        """Rate a marketplace service (1-5)."""
        params: dict[str, Any] = {
            "service_id": service_id,
            "agent_id": agent_id,
            "rating": rating,
        }
        if review is not None:
            params["review"] = review
        result = await self.execute("rate_service", params)
        return RateServiceResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Trust
    # =====================================================================

    async def get_trust_score(
        self,
        server_id: str,
        window: str = "24h",
        recompute: bool = False,
    ) -> TrustScoreResponse:
        """Get trust score for a server."""
        result = await self.execute(
            "get_trust_score",
            {"server_id": server_id, "window": window, "recompute": recompute},
        )
        return TrustScoreResponse.from_dict(result.result)

    async def search_servers(
        self,
        name_contains: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> SearchServersResponse:
        """Search for servers by name or minimum trust score."""
        params: dict[str, Any] = {"limit": limit}
        if name_contains is not None:
            params["name_contains"] = name_contains
        if min_score is not None:
            params["min_score"] = min_score
        result = await self.execute("search_servers", params)
        return SearchServersResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Identity
    # =====================================================================

    async def register_agent(self, agent_id: str, public_key: str | None = None) -> RegisterAgentResponse:
        """Register a cryptographic identity for an agent."""
        params: dict[str, Any] = {"agent_id": agent_id}
        if public_key is not None:
            params["public_key"] = public_key
        result = await self.execute("register_agent", params)
        return RegisterAgentResponse.from_dict(result.result)

    async def get_agent_identity(self, agent_id: str) -> GetAgentIdentityResponse:
        """Get the cryptographic identity and public key for an agent."""
        result = await self.execute("get_agent_identity", {"agent_id": agent_id})
        return GetAgentIdentityResponse.from_dict(result.result)

    async def verify_agent(self, agent_id: str, message: str, signature: str) -> VerifyAgentResponse:
        """Verify that a message was signed by the claimed agent."""
        result = await self.execute(
            "verify_agent",
            {"agent_id": agent_id, "message": message, "signature": signature},
        )
        return VerifyAgentResponse.from_dict(result.result)

    async def submit_metrics(
        self,
        agent_id: str,
        metrics: dict[str, Any],
        data_source: str = "self_reported",
    ) -> SubmitMetricsResponse:
        """Submit trading bot metrics for platform attestation."""
        result = await self.execute(
            "submit_metrics",
            {"agent_id": agent_id, "metrics": metrics, "data_source": data_source},
        )
        return SubmitMetricsResponse.from_dict(result.result)

    async def get_verified_claims(self, agent_id: str) -> GetVerifiedClaimsResponse:
        """Get all verified metric claims for an agent."""
        result = await self.execute("get_verified_claims", {"agent_id": agent_id})
        return GetVerifiedClaimsResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Messaging
    # =====================================================================

    async def send_message(
        self,
        sender: str,
        recipient: str,
        message_type: str,
        body: str | None = None,
        subject: str | None = None,
        thread_id: str | None = None,
    ) -> SendMessageResponse:
        """Send a typed message to another agent."""
        params: dict[str, Any] = {
            "sender": sender,
            "recipient": recipient,
            "message_type": message_type,
        }
        if body is not None:
            params["body"] = body
        if subject is not None:
            params["subject"] = subject
        if thread_id is not None:
            params["thread_id"] = thread_id
        result = await self.execute("send_message", params)
        return SendMessageResponse.from_dict(result.result)

    async def get_messages(
        self,
        agent_id: str,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> GetMessagesResponse:
        """Get messages for an agent (sent and received)."""
        params: dict[str, Any] = {"agent_id": agent_id, "limit": limit}
        if thread_id is not None:
            params["thread_id"] = thread_id
        result = await self.execute("get_messages", params)
        return GetMessagesResponse.from_dict(result.result)

    async def negotiate_price(
        self,
        initiator: str,
        responder: str,
        amount: float,
        service_id: str | None = None,
        expires_hours: float = 24,
    ) -> NegotiatePriceResponse:
        """Start a price negotiation with another agent."""
        params: dict[str, Any] = {
            "initiator": initiator,
            "responder": responder,
            "amount": amount,
            "expires_hours": expires_hours,
        }
        if service_id is not None:
            params["service_id"] = service_id
        result = await self.execute("negotiate_price", params)
        return NegotiatePriceResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Webhooks
    # =====================================================================

    async def register_webhook(
        self,
        agent_id: str,
        url: str,
        event_types: list[str],
        secret: str | None = None,
        filter_agent_ids: list[str] | None = None,
    ) -> RegisterWebhookResponse:
        """Register a webhook endpoint to receive event notifications."""
        params: dict[str, Any] = {
            "agent_id": agent_id,
            "url": url,
            "event_types": event_types,
        }
        if secret is not None:
            params["secret"] = secret
        if filter_agent_ids is not None:
            params["filter_agent_ids"] = filter_agent_ids
        result = await self.execute("register_webhook", params)
        return RegisterWebhookResponse.from_dict(result.result)

    async def list_webhooks(self, agent_id: str) -> ListWebhooksResponse:
        """List all registered webhooks for an agent."""
        result = await self.execute("list_webhooks", {"agent_id": agent_id})
        return ListWebhooksResponse.from_dict(result.result)

    async def delete_webhook(self, webhook_id: str) -> DeleteWebhookResponse:
        """Delete (deactivate) a webhook by its ID."""
        result = await self.execute("delete_webhook", {"webhook_id": webhook_id})
        return DeleteWebhookResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — API Keys
    # =====================================================================

    async def create_api_key(self, agent_id: str, tier: str | None = None) -> CreateApiKeyResponse:
        """Create a new API key for an agent."""
        params: dict[str, Any] = {"agent_id": agent_id}
        if tier is not None:
            params["tier"] = tier
        result = await self.execute("create_api_key", params)
        return CreateApiKeyResponse.from_dict(result.result)

    async def rotate_key(self, current_key: str) -> RotateKeyResponse:
        """Rotate an API key: revoke the current key and create a new one."""
        result = await self.execute("rotate_key", {"current_key": current_key})
        return RotateKeyResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Events
    # =====================================================================

    async def publish_event(
        self,
        event_type: str,
        source: str,
        payload: dict[str, Any] | None = None,
    ) -> PublishEventResponse:
        """Publish an event to the cross-product event bus."""
        params: dict[str, Any] = {"event_type": event_type, "source": source}
        if payload is not None:
            params["payload"] = payload
        result = await self.execute("publish_event", params)
        return PublishEventResponse.from_dict(result.result)

    async def get_events(
        self,
        event_type: str | None = None,
        since_id: int = 0,
        limit: int = 100,
    ) -> GetEventsResponse:
        """Query events from the event bus."""
        params: dict[str, Any] = {"since_id": since_id, "limit": limit}
        if event_type is not None:
            params["event_type"] = event_type
        result = await self.execute("get_events", params)
        return GetEventsResponse.from_dict(result.result)

    # =====================================================================
    # Convenience methods — Org
    # =====================================================================

    async def create_org(self, org_name: str) -> CreateOrgResponse:
        """Create a new organization."""
        result = await self.execute("create_org", {"org_name": org_name})
        return CreateOrgResponse.from_dict(result.result)

    async def get_org(self, org_id: str) -> GetOrgResponse:
        """Get organization details and members."""
        result = await self.execute("get_org", {"org_id": org_id})
        return GetOrgResponse.from_dict(result.result)

    async def add_agent_to_org(self, org_id: str, agent_id: str) -> AddAgentToOrgResponse:
        """Add an agent to an organization."""
        result = await self.execute("add_agent_to_org", {"org_id": org_id, "agent_id": agent_id})
        return AddAgentToOrgResponse.from_dict(result.result)

    # ----- Batch execution -----

    async def batch_execute(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """POST /v1/batch — execute multiple tool calls in one request.

        Args:
            calls: List of {"tool": str, "params": dict} dicts.

        Returns:
            List of result dicts, one per call.
        """
        resp = await self._request_with_retry(
            "POST",
            "/v1/batch",
            json={"calls": calls},
            headers=self._headers(),
        )
        body = resp.json()
        if resp.status_code != 200:
            raise_for_status(resp.status_code, body)
        return body.get("results", [])
