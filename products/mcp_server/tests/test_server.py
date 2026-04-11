"""Tests for the MCP server wiring (tools/list + tools/call handlers)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from a2a_mcp_server.gateway_client import GatewayError
from a2a_mcp_server.server import build_server


@pytest.fixture
def fake_gateway_client():
    client = AsyncMock()
    client.list_tools = AsyncMock(
        return_value=[
            {
                "name": "get_balance",
                "service": "billing",
                "description": "Get wallet balance.",
                "input_schema": {
                    "type": "object",
                    "properties": {"agent_id": {"type": "string"}},
                    "required": ["agent_id"],
                },
                "pricing": {"per_call": 0.0},
                "tier_required": "free",
            }
        ]
    )
    client.invoke_tool = AsyncMock(return_value={"balance": 500, "currency": "USD"})
    return client


@pytest.mark.asyncio
async def test_server_build_returns_mcp_server(fake_gateway_client):
    server = build_server(fake_gateway_client)
    assert server.name == "a2a-mcp-server"


@pytest.mark.asyncio
async def test_server_list_tools_returns_gateway_catalog(fake_gateway_client):
    server = build_server(fake_gateway_client)
    tools = await _call_list_tools(server)
    assert len(tools) == 1
    assert tools[0].name == "get_balance"
    fake_gateway_client.list_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_server_call_tool_forwards_to_gateway(fake_gateway_client):
    server = build_server(fake_gateway_client)
    content = await _call_tool(server, "get_balance", {"agent_id": "alice"})
    fake_gateway_client.invoke_tool.assert_awaited_once_with("get_balance", {"agent_id": "alice"})
    # Result must be serialised as TextContent with JSON payload
    assert len(content) == 1
    assert content[0].type == "text"
    payload = json.loads(content[0].text)
    assert payload["balance"] == 500


@pytest.mark.asyncio
async def test_server_list_tools_caches_catalog_within_ttl(fake_gateway_client):
    """A second ``tools/list`` within the TTL must not re-hit the gateway."""
    server = build_server(fake_gateway_client)
    await _call_list_tools(server)
    await _call_list_tools(server)
    # Only called once — the second call is served from the in-process cache.
    assert fake_gateway_client.list_tools.await_count == 1


@pytest.mark.asyncio
async def test_server_list_tools_refreshes_after_ttl_expiry(fake_gateway_client, monkeypatch):
    """After the TTL elapses, the catalog is fetched again."""
    import a2a_mcp_server.server as server_mod

    current = {"t": 1000.0}
    monkeypatch.setattr(server_mod.time, "monotonic", lambda: current["t"])

    server = build_server(fake_gateway_client)
    await _call_list_tools(server)  # t=1000 → fetch (cache expires at 1010)
    current["t"] = 2000.0
    await _call_list_tools(server)  # t=2000 → TTL expired → refetch
    assert fake_gateway_client.list_tools.await_count == 2


@pytest.mark.asyncio
async def test_server_call_tool_wraps_gateway_error_as_text_content(fake_gateway_client):
    """A ``GatewayError`` from ``invoke_tool`` is returned as JSON text content."""
    fake_gateway_client.invoke_tool = AsyncMock(side_effect=GatewayError("[rate_limited] slow down"))
    server = build_server(fake_gateway_client)
    content = await _call_tool(server, "get_balance", {"agent_id": "alice"})

    assert len(content) == 1
    assert content[0].type == "text"
    payload = json.loads(content[0].text)
    assert "error" in payload
    assert "rate_limited" in payload["error"]


@pytest.mark.asyncio
async def test_server_call_tool_non_dict_result_returns_text_content(fake_gateway_client):
    """Non-dict results (lists, scalars) serialize to TextContent rather than structured content."""
    fake_gateway_client.invoke_tool = AsyncMock(return_value=["a", "b", "c"])
    server = build_server(fake_gateway_client)
    content = await _call_tool(server, "list_agents", {})

    assert isinstance(content, list)
    assert len(content) == 1
    assert content[0].type == "text"
    assert json.loads(content[0].text) == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_server_call_tool_dict_result_serializes_nonjson_values(fake_gateway_client):
    """Dict results containing Decimal/datetime are coerced to strings via ``default=str``."""
    from datetime import datetime
    from decimal import Decimal

    fake_gateway_client.invoke_tool = AsyncMock(
        return_value={
            "amount": Decimal("12.34"),
            "created_at": datetime(2026, 4, 11, 12, 0, 0),
        }
    )
    server = build_server(fake_gateway_client)
    content = await _call_tool(server, "get_intent", {"intent_id": "int-1"})

    # Structured content path → gets re-rendered by the MCP SDK as TextContent
    # with the JSON payload; either shape is acceptable, but both must round-trip.
    assert content, "expected at least one content element"
    text = content[0].text
    payload = json.loads(text)
    assert payload["amount"] == "12.34"
    assert payload["created_at"].startswith("2026-04-11")


@pytest.mark.asyncio
async def test_server_call_tool_defaults_arguments_to_empty_dict(fake_gateway_client):
    """Our callback guards ``arguments or {}`` — verify via a direct call.

    The public MCP path normalises ``None → {}`` in the SDK before reaching
    our handler and then validates against the tool's input schema (which
    requires ``agent_id``). So we pull the decorated callback out by name
    and invoke it directly to cover the defensive guard.
    """
    import inspect

    server = build_server(fake_gateway_client)
    # The SDK stores the decorated function under the request handler's
    # closure. Walk the closure and find the first async function — that's
    # our ``_call_tool`` inner function.
    from mcp.types import CallToolRequest

    wrapper = server.request_handlers[CallToolRequest]
    inner = None
    for cell in wrapper.__closure__ or ():
        val = cell.cell_contents
        if inspect.iscoroutinefunction(val) and val.__name__ == "_call_tool":
            inner = val
            break
    assert inner is not None, "could not locate inner _call_tool callback"

    result = await inner("get_balance", None)
    # Result is a dict (structured content) because invoke_tool returns a dict.
    assert result == {"balance": 500, "currency": "USD"}
    fake_gateway_client.invoke_tool.assert_awaited_once_with("get_balance", {})


# ---------------------------------------------------------------------------
# Helpers that invoke the MCP low-level Server handlers directly (the SDK
# wires them via decorators, so we pull them out by request type).
# ---------------------------------------------------------------------------


async def _call_list_tools(server):
    from mcp.types import ListToolsRequest

    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return result.root.tools


async def _call_tool(server, name, arguments):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server.request_handlers[CallToolRequest]
    result = await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=arguments),
        )
    )
    return result.root.content
