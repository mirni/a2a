"""Thin async HTTP client for the A2A Commerce Gateway.

Only exposes what the MCP server needs:

  * ``list_tools()`` — fetch the full tool catalogue from ``GET /v1/pricing``
  * ``invoke_tool(name, params)`` — execute a single tool via ``POST /v1/batch``

``/v1/batch`` is used rather than the legacy ``/v1/execute`` endpoint because
the latter is restricted to connector tools in v1.2+, while batch accepts
every tool registered in the gateway's ``TOOL_REGISTRY``.
"""

from __future__ import annotations

from typing import Any

import httpx

from a2a_mcp_server._version import __version__

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class GatewayError(RuntimeError):
    """Raised when the gateway returns an error result."""


class GatewayAuthError(GatewayError):
    """Raised when the gateway rejects the API key (401/403)."""


class GatewayRateLimitError(GatewayError):
    """Raised when the gateway returns 429 Too Many Requests."""


class GatewayClient:
    """Async HTTP client for the A2A gateway, scoped to MCP server needs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: httpx.Timeout | float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout or _DEFAULT_TIMEOUT,
            transport=transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": user_agent or f"a2a-mcp-server/{__version__}",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GatewayClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def list_tools(self) -> list[dict[str, Any]]:
        """GET /v1/pricing → list of catalog tool definitions."""
        resp = await self._client.get("/v1/pricing")
        _raise_for_status(resp)
        body = resp.json()
        tools = body.get("tools") if isinstance(body, dict) else None
        if not isinstance(tools, list):
            raise GatewayError(f"Unexpected /v1/pricing payload shape: {body!r}")
        return tools

    async def invoke_tool(self, name: str, params: dict[str, Any] | None = None) -> Any:
        """POST /v1/batch with a single call — unwraps and returns the result."""
        payload = {"calls": [{"tool": name, "params": params or {}}]}
        resp = await self._client.post("/v1/batch", json=payload)
        _raise_for_status(resp)
        body = resp.json()
        results = body.get("results") if isinstance(body, dict) else None
        if not results or not isinstance(results, list):
            raise GatewayError(f"Unexpected /v1/batch payload shape: {body!r}")
        first = results[0]
        if first.get("success"):
            return first.get("result")
        err = first.get("error") or {}
        code = err.get("code", "gateway_error")
        message = err.get("message", "Unknown gateway error")
        raise GatewayError(f"[{code}] {message}")


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 401 or resp.status_code == 403:
        raise GatewayAuthError(_extract_message(resp) or "Gateway rejected API key")
    if resp.status_code == 429:
        raise GatewayRateLimitError(_extract_message(resp) or "Gateway rate limit exceeded")
    if resp.status_code >= 400:
        raise GatewayError(f"Gateway returned {resp.status_code}: {_extract_message(resp) or resp.text}")


def _extract_message(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return err.get("message")
        if isinstance(body.get("detail"), str):
            return body["detail"]
    return None
