"""Tests for the A2A gateway HTTP client used by the MCP server."""

from __future__ import annotations

import httpx
import pytest
from a2a_mcp_server.gateway_client import (
    GatewayAuthError,
    GatewayClient,
    GatewayError,
    GatewayRateLimitError,
)


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_gateway_client_list_tools_calls_pricing_with_auth_header():
    """list_tools() GETs /v1/pricing with Authorization: Bearer <key>."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "tools": [
                    {
                        "name": "get_balance",
                        "service": "billing",
                        "description": "Get balance",
                        "input_schema": {"type": "object", "properties": {}, "required": []},
                        "pricing": {"per_call": 0.0},
                        "tier_required": "free",
                    }
                ]
            },
        )

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        tools = await client.list_tools()
    finally:
        await client.close()

    assert len(tools) == 1
    assert tools[0]["name"] == "get_balance"
    assert captured["auth"] == "Bearer a2a_test_abc"
    assert "/v1/pricing" in captured["url"]


@pytest.mark.asyncio
async def test_gateway_client_invoke_tool_calls_batch_endpoint():
    """invoke_tool() POSTs a single call to /v1/batch and unwraps the result."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"results": [{"success": True, "result": {"balance": 500}}]},
        )

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        result = await client.invoke_tool("get_balance", {"agent_id": "alice"})
    finally:
        await client.close()

    assert result == {"balance": 500}
    assert captured["method"] == "POST"
    assert "/v1/batch" in captured["url"]
    assert "get_balance" in captured["body"]
    assert "alice" in captured["body"]


@pytest.mark.asyncio
async def test_gateway_client_invoke_tool_raises_on_error_result():
    """invoke_tool() raises GatewayError when the batch result has success=False."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "success": False,
                        "error": {"code": "unknown_tool", "message": "Unknown tool: foo"},
                    }
                ]
            },
        )

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError) as excinfo:
            await client.invoke_tool("foo", {})
    finally:
        await client.close()

    assert "Unknown tool" in str(excinfo.value)


@pytest.mark.asyncio
async def test_gateway_client_raises_auth_error_on_401():
    """401 from /v1/pricing raises GatewayAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Missing API key"}})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="bad_key",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayAuthError):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_raises_rate_limit_error_on_429():
    """429 from /v1/batch raises GatewayRateLimitError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayRateLimitError):
            await client.invoke_tool("get_balance", {})
    finally:
        await client.close()
