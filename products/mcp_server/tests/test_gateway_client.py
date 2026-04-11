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


@pytest.mark.asyncio
async def test_gateway_client_strips_trailing_slash_from_base_url():
    """A trailing slash on ``base_url`` is normalised away."""

    def handler(request: httpx.Request) -> httpx.Response:
        # httpx joins base + path, so a stray slash would produce //v1/pricing.
        assert "//v1/pricing" not in str(request.url)
        return httpx.Response(200, json={"tools": []})

    client = GatewayClient(
        base_url="https://api.greenhelix.net/",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        tools = await client.list_tools()
    finally:
        await client.close()
    assert tools == []


@pytest.mark.asyncio
async def test_gateway_client_uses_custom_user_agent():
    """``user_agent`` kwarg overrides the default a2a-mcp-server UA string."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"tools": []})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        user_agent="custom-agent/9.9",
        transport=_mock_transport(handler),
    )
    try:
        await client.list_tools()
    finally:
        await client.close()
    assert captured["ua"] == "custom-agent/9.9"


@pytest.mark.asyncio
async def test_gateway_client_default_user_agent_contains_version():
    """When no UA is provided, the default is ``a2a-mcp-server/<version>``."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json={"tools": []})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        await client.list_tools()
    finally:
        await client.close()
    assert captured["ua"].startswith("a2a-mcp-server/")


@pytest.mark.asyncio
async def test_gateway_client_context_manager_closes():
    """``async with GatewayClient(...)`` closes the underlying httpx client."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tools": []})

    async with GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    ) as client:
        tools = await client.list_tools()
    assert tools == []
    # After exit, subsequent calls must fail because the client is closed.
    with pytest.raises(RuntimeError):
        await client.list_tools()


@pytest.mark.asyncio
async def test_gateway_client_list_tools_rejects_non_list_tools_field():
    """A /v1/pricing body whose ``tools`` field is not a list → GatewayError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tools": {"not": "a list"}})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="Unexpected /v1/pricing payload"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_list_tools_rejects_non_dict_body():
    """A /v1/pricing body that is not even a dict raises GatewayError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="Unexpected /v1/pricing payload"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_invoke_tool_rejects_missing_results():
    """A /v1/batch body without a ``results`` list raises GatewayError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": None})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="Unexpected /v1/batch payload"):
            await client.invoke_tool("get_balance", {})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_invoke_tool_empty_results():
    """A /v1/batch body with an empty ``results`` list raises GatewayError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="Unexpected /v1/batch payload"):
            await client.invoke_tool("get_balance", {})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_invoke_tool_with_default_params():
    """``invoke_tool`` without params sends an empty object."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"results": [{"success": True, "result": "ok"}]})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        result = await client.invoke_tool("ping")
    finally:
        await client.close()

    assert result == "ok"
    assert '"params": {}' in captured["body"] or '"params":{}' in captured["body"]


@pytest.mark.asyncio
async def test_gateway_client_error_without_error_object_uses_default_message():
    """A success=False result with no ``error`` object still raises with a default message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"success": False}]})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="Unknown gateway error"):
            await client.invoke_tool("foo", {})
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_raises_generic_error_on_500():
    """5xx responses bubble up as plain GatewayError with status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="500"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_raises_auth_error_on_403():
    """403 also maps to GatewayAuthError (not just 401)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Forbidden"}})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayAuthError, match="Forbidden"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_extract_message_handles_invalid_json():
    """Non-JSON error body falls back to the raw text."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>oops</html>")

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="oops"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_extract_message_uses_detail_string():
    """Pydantic-style ``{"detail": "..."}`` body surfaces as the error message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "agent_id is required"})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="agent_id is required"):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_extract_message_handles_missing_message_field():
    """401 with a JSON body that lacks ``error.message`` uses the default."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {}})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayAuthError):
            await client.list_tools()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_client_extract_message_falls_through_on_unknown_dict():
    """JSON dict body with neither error-dict nor detail-string → default msg."""

    def handler(request: httpx.Request) -> httpx.Response:
        # error is a string (not dict), detail is an int (not str) → fall through
        return httpx.Response(500, json={"error": "oops", "detail": 42})

    client = GatewayClient(
        base_url="https://api.greenhelix.net",
        api_key="a2a_test_abc",
        transport=_mock_transport(handler),
    )
    try:
        with pytest.raises(GatewayError, match="500"):
            await client.list_tools()
    finally:
        await client.close()
