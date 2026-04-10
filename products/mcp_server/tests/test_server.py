"""Tests for the MCP server wiring (tools/list + tools/call handlers)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

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
    handler = server.request_handlers
    # Look up ListToolsRequest handler via public API
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
