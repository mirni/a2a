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
    SubmitVerificationResponse,
    SubscriptionResponse,
    ToolPricing,
    TrustScoreResponse,
    VerificationJobResponse,
    VerifyAgentResponse,
    VerifyProofResponse,
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

    async def _rest(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Call a REST endpoint with auth, error handling, and JSON parsing."""
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)
        kwargs: dict[str, Any] = {"headers": headers}
        if json is not None:
            kwargs["json"] = json
        if params is not None:
            # Filter out None values
            kwargs["params"] = {k: v for k, v in params.items() if v is not None}
        resp = await self._request_with_retry(method, path, **kwargs)
        body = resp.json()
        if resp.status_code >= 400:
            raise_for_status(resp.status_code, body)
        return body

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
        data = await self._rest("GET", f"/v1/billing/wallets/{agent_id}/balance")
        return BalanceResponse.from_dict(data)

    async def deposit(self, agent_id: str, amount: float, description: str = "") -> DepositResponse:
        """Deposit credits into a wallet. Returns new balance."""
        data = await self._rest(
            "POST",
            f"/v1/billing/wallets/{agent_id}/deposit",
            json={"amount": amount, "description": description},
        )
        return DepositResponse.from_dict(data)

    async def get_usage_summary(self, agent_id: str, since: float | None = None) -> dict[str, Any]:
        """Get usage summary for an agent."""
        p: dict[str, Any] = {}
        if since is not None:
            p["since"] = since
        return await self._rest("GET", f"/v1/billing/wallets/{agent_id}/usage", params=p)

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
        body: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "description": description,
        }
        extra: dict[str, str] = {}
        if idempotency_key:
            extra["Idempotency-Key"] = idempotency_key
        data = await self._rest("POST", "/v1/payments/intents", json=body, extra_headers=extra or None)
        return PaymentIntentResponse.from_dict(data)

    async def capture_payment(self, intent_id: str) -> PaymentIntentResponse:
        """Capture a pending payment intent."""
        data = await self._rest("POST", f"/v1/payments/intents/{intent_id}/capture")
        return PaymentIntentResponse.from_dict(data)

    async def void_payment(self, intent_id: str) -> VoidPaymentResponse:
        """Void (refund) a payment intent."""
        data = await self._rest("POST", f"/v1/payments/intents/{intent_id}/refund")
        return VoidPaymentResponse.from_dict(data)

    async def refund_settlement(
        self,
        settlement_id: str,
        amount: float | None = None,
        reason: str | None = None,
    ) -> RefundSettlementResponse:
        """Refund a settled payment (full or partial)."""
        body: dict[str, Any] = {}
        if amount is not None:
            body["amount"] = amount
        if reason is not None:
            body["reason"] = reason
        data = await self._rest(
            "POST",
            f"/v1/payments/settlements/{settlement_id}/refund",
            json=body or None,
        )
        return RefundSettlementResponse.from_dict(data)

    async def get_payment_history(self, agent_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get payment history for an agent."""
        data = await self._rest(
            "GET",
            "/v1/payments/history",
            params={"agent_id": agent_id, "limit": limit, "offset": offset},
        )
        return data["history"]

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
        body: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "description": description,
        }
        if timeout_hours is not None:
            body["timeout_hours"] = timeout_hours
        data = await self._rest("POST", "/v1/payments/escrows", json=body)
        return EscrowResponse.from_dict(data)

    async def release_escrow(self, escrow_id: str) -> EscrowResponse:
        """Release an escrow to the payee."""
        data = await self._rest("POST", f"/v1/payments/escrows/{escrow_id}/release")
        return EscrowResponse.from_dict(data)

    async def cancel_escrow(self, escrow_id: str) -> CancelEscrowResponse:
        """Cancel a held escrow and refund the payer."""
        data = await self._rest("POST", f"/v1/payments/escrows/{escrow_id}/cancel")
        return CancelEscrowResponse.from_dict(data)

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
        body: dict[str, Any] = {
            "payer": payer,
            "payee": payee,
            "amount": amount,
            "interval": interval,
        }
        if description:
            body["description"] = description
        data = await self._rest("POST", "/v1/payments/subscriptions", json=body)
        return SubscriptionResponse.from_dict(data)

    async def cancel_subscription(
        self,
        subscription_id: str,
        cancelled_by: str | None = None,
    ) -> CancelSubscriptionResponse:
        """Cancel an active or suspended subscription."""
        body: dict[str, Any] = {}
        if cancelled_by is not None:
            body["cancelled_by"] = cancelled_by
        data = await self._rest(
            "POST",
            f"/v1/payments/subscriptions/{subscription_id}/cancel",
            json=body or None,
        )
        return CancelSubscriptionResponse.from_dict(data)

    async def get_subscription(self, subscription_id: str) -> GetSubscriptionResponse:
        """Get details of a subscription by ID."""
        data = await self._rest("GET", f"/v1/payments/subscriptions/{subscription_id}")
        return GetSubscriptionResponse.from_dict(data)

    async def list_subscriptions(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> ListSubscriptionsResponse:
        """List subscriptions for an agent."""
        data = await self._rest(
            "GET",
            "/v1/payments/subscriptions",
            params={"agent_id": agent_id, "status": status, "limit": limit, "offset": offset},
        )
        return ListSubscriptionsResponse.from_dict(data)

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
        body: dict[str, Any] = {
            "provider_id": provider_id,
            "name": name,
            "description": description,
            "category": category,
        }
        if tools is not None:
            body["tools"] = tools
        if tags is not None:
            body["tags"] = tags
        if endpoint is not None:
            body["endpoint"] = endpoint
        if pricing is not None:
            body["pricing"] = pricing
        data = await self._rest("POST", "/v1/marketplace/services", json=body)
        return RegisterServiceResponse.from_dict(data)

    async def search_services(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        max_cost: float | None = None,
        limit: int = 20,
    ) -> SearchServicesResponse:
        """Search the marketplace."""
        p: dict[str, Any] = {"limit": limit}
        if query:
            p["query"] = query
        if category:
            p["category"] = category
        if tags:
            p["tags"] = ",".join(tags)
        if max_cost is not None:
            p["max_cost"] = max_cost
        data = await self._rest("GET", "/v1/marketplace/services", params=p)
        return SearchServicesResponse.from_dict(data)

    async def best_match(
        self,
        query: str,
        budget: float | None = None,
        min_trust_score: float | None = None,
        prefer: str = "trust",
        limit: int = 5,
    ) -> list[ServiceMatch]:
        """Find best matching services."""
        p: dict[str, Any] = {"query": query, "prefer": prefer, "limit": limit}
        if budget is not None:
            p["budget"] = budget
        if min_trust_score is not None:
            p["min_trust_score"] = min_trust_score
        data = await self._rest("GET", "/v1/marketplace/match", params=p)
        return [ServiceMatch.from_dict(m) for m in data["matches"]]

    async def get_service(self, service_id: str) -> GetServiceResponse:
        """Get a marketplace service by its ID."""
        data = await self._rest("GET", f"/v1/marketplace/services/{service_id}")
        return GetServiceResponse.from_dict(data)

    async def rate_service(
        self,
        service_id: str,
        agent_id: str,
        rating: int,
        review: str | None = None,
    ) -> RateServiceResponse:
        """Rate a marketplace service (1-5)."""
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "rating": rating,
        }
        if review is not None:
            body["review"] = review
        data = await self._rest("POST", f"/v1/marketplace/services/{service_id}/ratings", json=body)
        return RateServiceResponse.from_dict(data)

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
        p: dict[str, Any] = {"window": window}
        if recompute:
            p["recompute"] = "true"
        data = await self._rest("GET", f"/v1/trust/servers/{server_id}/score", params=p)
        return TrustScoreResponse.from_dict(data)

    async def search_servers(
        self,
        name_contains: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> SearchServersResponse:
        """Search for servers by name or minimum trust score."""
        p: dict[str, Any] = {"limit": limit}
        if name_contains is not None:
            p["name_contains"] = name_contains
        if min_score is not None:
            p["min_score"] = min_score
        data = await self._rest("GET", "/v1/trust/servers", params=p)
        return SearchServersResponse.from_dict(data)

    # =====================================================================
    # Convenience methods — Identity
    # =====================================================================

    async def register_agent(self, agent_id: str, public_key: str | None = None) -> RegisterAgentResponse:
        """Register a cryptographic identity for an agent."""
        body: dict[str, Any] = {"agent_id": agent_id}
        if public_key is not None:
            body["public_key"] = public_key
        data = await self._rest("POST", "/v1/identity/agents", json=body)
        return RegisterAgentResponse.from_dict(data)

    async def get_agent_identity(self, agent_id: str) -> GetAgentIdentityResponse:
        """Get the cryptographic identity and public key for an agent."""
        data = await self._rest("GET", f"/v1/identity/agents/{agent_id}")
        return GetAgentIdentityResponse.from_dict(data)

    async def verify_agent(self, agent_id: str, message: str, signature: str) -> VerifyAgentResponse:
        """Verify that a message was signed by the claimed agent."""
        data = await self._rest(
            "POST",
            f"/v1/identity/agents/{agent_id}/verify",
            json={"message": message, "signature": signature},
        )
        return VerifyAgentResponse.from_dict(data)

    async def submit_metrics(
        self,
        agent_id: str,
        metrics: dict[str, Any],
        data_source: str = "self_reported",
    ) -> SubmitMetricsResponse:
        """Submit trading bot metrics for platform attestation."""
        data = await self._rest(
            "POST",
            f"/v1/identity/agents/{agent_id}/metrics",
            json={"metrics": metrics, "data_source": data_source},
        )
        return SubmitMetricsResponse.from_dict(data)

    async def get_verified_claims(self, agent_id: str) -> GetVerifiedClaimsResponse:
        """Get all verified metric claims for an agent."""
        data = await self._rest("GET", f"/v1/identity/agents/{agent_id}/claims")
        return GetVerifiedClaimsResponse.from_dict(data)

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
        json_body: dict[str, Any] = {
            "sender": sender,
            "recipient": recipient,
            "message_type": message_type,
        }
        if body is not None:
            json_body["body"] = body
        if subject is not None:
            json_body["subject"] = subject
        if thread_id is not None:
            json_body["thread_id"] = thread_id
        data = await self._rest("POST", "/v1/messaging/messages", json=json_body)
        return SendMessageResponse.from_dict(data)

    async def get_messages(
        self,
        agent_id: str,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> GetMessagesResponse:
        """Get messages for an agent (sent and received)."""
        p: dict[str, Any] = {"agent_id": agent_id, "limit": limit}
        if thread_id is not None:
            p["thread_id"] = thread_id
        data = await self._rest("GET", "/v1/messaging/messages", params=p)
        return GetMessagesResponse.from_dict(data)

    async def negotiate_price(
        self,
        initiator: str,
        responder: str,
        amount: float,
        service_id: str | None = None,
        expires_hours: float = 24,
    ) -> NegotiatePriceResponse:
        """Start a price negotiation with another agent."""
        body: dict[str, Any] = {
            "initiator": initiator,
            "responder": responder,
            "amount": amount,
            "expires_hours": expires_hours,
        }
        if service_id is not None:
            body["service_id"] = service_id
        data = await self._rest("POST", "/v1/messaging/negotiations", json=body)
        return NegotiatePriceResponse.from_dict(data)

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
        body: dict[str, Any] = {
            "url": url,
            "event_types": event_types,
        }
        if secret is not None:
            body["secret"] = secret
        if filter_agent_ids is not None:
            body["filter_agent_ids"] = filter_agent_ids
        data = await self._rest("POST", "/v1/infra/webhooks", json=body)
        return RegisterWebhookResponse.from_dict(data)

    async def list_webhooks(self, agent_id: str) -> ListWebhooksResponse:
        """List all registered webhooks for an agent."""
        data = await self._rest("GET", "/v1/infra/webhooks")
        return ListWebhooksResponse.from_dict(data)

    async def delete_webhook(self, webhook_id: str) -> DeleteWebhookResponse:
        """Delete (deactivate) a webhook by its ID."""
        data = await self._rest("DELETE", f"/v1/infra/webhooks/{webhook_id}")
        return DeleteWebhookResponse.from_dict(data)

    # =====================================================================
    # Convenience methods — API Keys
    # =====================================================================

    async def create_api_key(self, agent_id: str, tier: str | None = None) -> CreateApiKeyResponse:
        """Create a new API key for an agent."""
        body: dict[str, Any] = {}
        if tier is not None:
            body["tier"] = tier
        data = await self._rest("POST", "/v1/infra/keys", json=body)
        return CreateApiKeyResponse.from_dict(data)

    async def rotate_key(self, current_key: str) -> RotateKeyResponse:
        """Rotate an API key: revoke the current key and create a new one."""
        data = await self._rest("POST", "/v1/infra/keys/rotate", json={"current_key": current_key})
        return RotateKeyResponse.from_dict(data)

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
        body: dict[str, Any] = {"event_type": event_type, "source": source}
        if payload is not None:
            body["payload"] = payload
        data = await self._rest("POST", "/v1/infra/events", json=body)
        return PublishEventResponse.from_dict(data)

    async def get_events(
        self,
        event_type: str | None = None,
        since_id: int = 0,
        limit: int = 100,
    ) -> GetEventsResponse:
        """Query events from the event bus."""
        p: dict[str, Any] = {"since_id": since_id, "limit": limit}
        if event_type is not None:
            p["event_type"] = event_type
        data = await self._rest("GET", "/v1/infra/events", params=p)
        return GetEventsResponse.from_dict(data)

    # =====================================================================
    # Convenience methods — Org
    # =====================================================================

    async def create_org(self, org_name: str) -> CreateOrgResponse:
        """Create a new organization."""
        data = await self._rest("POST", "/v1/identity/orgs", json={"org_name": org_name})
        return CreateOrgResponse.from_dict(data)

    async def get_org(self, org_id: str) -> GetOrgResponse:
        """Get organization details and members."""
        data = await self._rest("GET", f"/v1/identity/orgs/{org_id}")
        return GetOrgResponse.from_dict(data)

    async def add_agent_to_org(self, org_id: str, agent_id: str) -> AddAgentToOrgResponse:
        """Add an agent to an organization."""
        data = await self._rest("POST", f"/v1/identity/orgs/{org_id}/members", json={"agent_id": agent_id})
        return AddAgentToOrgResponse.from_dict(data)

    # =====================================================================
    # Convenience methods — Gatekeeper (formal verifier)
    # =====================================================================

    async def submit_verification(
        self,
        agent_id: str,
        properties: list[dict[str, Any]],
        *,
        scope: str = "economic",
        timeout_seconds: int = 300,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SubmitVerificationResponse:
        """POST /v1/gatekeeper/jobs — submit a formal verification job.

        See :mod:`a2a_client.verifier` for the high-level one-liner.
        """
        body: dict[str, Any] = {
            "agent_id": agent_id,
            "properties": properties,
            "scope": scope,
            "timeout_seconds": timeout_seconds,
        }
        if webhook_url is not None:
            body["webhook_url"] = webhook_url
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        if metadata is not None:
            body["metadata"] = metadata
        data = await self._rest("POST", "/v1/gatekeeper/jobs", json=body)
        return SubmitVerificationResponse.from_dict(data)

    async def get_verification_status(self, job_id: str) -> VerificationJobResponse:
        """GET /v1/gatekeeper/jobs/{job_id} — job + result."""
        data = await self._rest("GET", f"/v1/gatekeeper/jobs/{job_id}")
        return VerificationJobResponse.from_dict(data)

    async def cancel_verification(self, job_id: str) -> VerificationJobResponse:
        """POST /v1/gatekeeper/jobs/{job_id}/cancel — cancel a pending job."""
        data = await self._rest("POST", f"/v1/gatekeeper/jobs/{job_id}/cancel")
        return VerificationJobResponse.from_dict(data)

    async def list_verification_jobs(
        self,
        agent_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """GET /v1/gatekeeper/jobs — list jobs for an agent."""
        params: dict[str, Any] = {"agent_id": agent_id, "limit": limit}
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        return await self._rest("GET", "/v1/gatekeeper/jobs", params=params)

    async def verify_proof(self, proof_hash: str) -> VerifyProofResponse:
        """POST /v1/gatekeeper/proofs/verify — check a proof by hash.

        Free-tier endpoint; intended for third parties to verify a
        proof without holding a pro key.
        """
        data = await self._rest(
            "POST",
            "/v1/gatekeeper/proofs/verify",
            json={"proof_hash": proof_hash},
        )
        return VerifyProofResponse.from_dict(data)

    async def get_proof(self, proof_id: str) -> dict[str, Any]:
        """GET /v1/gatekeeper/proofs/{proof_id} — fetch full proof artifact."""
        return await self._rest("GET", f"/v1/gatekeeper/proofs/{proof_id}")

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
