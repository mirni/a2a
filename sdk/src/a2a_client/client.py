"""A2A Commerce Python SDK client."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .errors import (
    A2AError,
    RETRYABLE_STATUS_CODES,
    RateLimitError,
    raise_for_status,
)
from .models import ExecuteResponse, HealthResponse, ToolPricing


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
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                if resp.status_code not in RETRYABLE_STATUS_CODES:
                    return resp
                # Retryable HTTP status — treat as error for retry
                if attempt == self.max_retries:
                    return resp  # Return the response on last attempt
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
                last_error = e
                if attempt == self.max_retries:
                    raise
            else:
                last_error = None

            # Compute delay
            delay = self.retry_base_delay * (2 ** attempt)

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
        if (
            use_cache
            and self._pricing_cache is not None
            and (now - self._pricing_cache_time) < self.pricing_cache_ttl
        ):
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

    async def execute(
        self, tool: str, params: dict[str, Any] | None = None
    ) -> ExecuteResponse:
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

    # ----- Convenience methods -----

    async def get_balance(self, agent_id: str) -> float:
        """Get wallet balance for an agent."""
        result = await self.execute("get_balance", {"agent_id": agent_id})
        return result.result["balance"]

    async def deposit(
        self, agent_id: str, amount: float, description: str = ""
    ) -> float:
        """Deposit credits into a wallet. Returns new balance."""
        result = await self.execute(
            "deposit", {"agent_id": agent_id, "amount": amount, "description": description}
        )
        return result.result["new_balance"]

    async def get_usage_summary(
        self, agent_id: str, since: float | None = None
    ) -> dict[str, Any]:
        """Get usage summary for an agent."""
        params: dict[str, Any] = {"agent_id": agent_id}
        if since is not None:
            params["since"] = since
        result = await self.execute("get_usage_summary", params)
        return result.result

    async def create_payment_intent(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
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
        return result.result

    async def capture_payment(self, intent_id: str) -> dict[str, Any]:
        """Capture a pending payment intent."""
        result = await self.execute("capture_intent", {"intent_id": intent_id})
        return result.result

    async def create_escrow(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        timeout_hours: float | None = None,
    ) -> dict[str, Any]:
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
        return result.result

    async def release_escrow(self, escrow_id: str) -> dict[str, Any]:
        """Release an escrow to the payee."""
        result = await self.execute("release_escrow", {"escrow_id": escrow_id})
        return result.result

    async def search_services(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        max_cost: float | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
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
        return result.result["services"]

    async def best_match(
        self,
        query: str,
        budget: float | None = None,
        min_trust_score: float | None = None,
        prefer: str = "trust",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find best matching services."""
        params: dict[str, Any] = {"query": query, "prefer": prefer, "limit": limit}
        if budget is not None:
            params["budget"] = budget
        if min_trust_score is not None:
            params["min_trust_score"] = min_trust_score
        result = await self.execute("best_match", params)
        return result.result["matches"]

    async def get_trust_score(
        self,
        server_id: str,
        window: str = "24h",
        recompute: bool = False,
    ) -> dict[str, Any]:
        """Get trust score for a server."""
        result = await self.execute(
            "get_trust_score",
            {"server_id": server_id, "window": window, "recompute": recompute},
        )
        return result.result

    async def get_payment_history(
        self, agent_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Get payment history for an agent."""
        result = await self.execute(
            "get_payment_history",
            {"agent_id": agent_id, "limit": limit, "offset": offset},
        )
        return result.result["history"]

    # ----- Batch execution -----

    async def batch_execute(
        self, calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
