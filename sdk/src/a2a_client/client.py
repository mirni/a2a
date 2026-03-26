"""A2A Commerce Python SDK client."""

from __future__ import annotations

from typing import Any

import httpx

from .errors import A2AError, raise_for_status
from .models import ExecuteResponse, HealthResponse, ToolPricing


class A2AClient:
    """Async client for the A2A Commerce gateway.

    Usage::

        async with A2AClient("http://localhost:8000", api_key="a2a_free_...") as client:
            health = await client.health()
            balance = await client.get_balance("my-agent")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
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

    # ----- Core methods -----

    async def health(self) -> HealthResponse:
        """GET /health"""
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return HealthResponse.from_dict(resp.json())

    async def pricing(self) -> list[ToolPricing]:
        """GET /pricing — full catalog."""
        resp = await self._client.get("/pricing")
        resp.raise_for_status()
        return [ToolPricing.from_dict(t) for t in resp.json()["tools"]]

    async def pricing_tool(self, tool_name: str) -> ToolPricing:
        """GET /pricing/{tool} — single tool."""
        resp = await self._client.get(f"/pricing/{tool_name}")
        if resp.status_code != 200:
            raise_for_status(resp.status_code, resp.json())
        return ToolPricing.from_dict(resp.json()["tool"])

    async def execute(
        self, tool: str, params: dict[str, Any] | None = None
    ) -> ExecuteResponse:
        """POST /execute — run a tool."""
        resp = await self._client.post(
            "/execute",
            json={"tool": tool, "params": params or {}},
            headers=self._headers(),
        )
        body = resp.json()
        if resp.status_code != 200:
            raise_for_status(resp.status_code, body)
        return ExecuteResponse.from_dict(body)

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
