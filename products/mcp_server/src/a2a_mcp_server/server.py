"""MCP low-level server wiring for a2a-mcp-server.

Exposes two handlers:

  * ``tools/list``  — fetch the gateway tool catalogue and convert to MCP
  * ``tools/call``  — forward the invocation to POST /v1/batch

The server is stateless; tool discovery happens on every ``tools/list`` so
that an agent always sees the latest catalogue. A small in-process cache
(10s TTL) prevents hammering the gateway when a client re-lists.
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import TextContent, Tool

from a2a_mcp_server._version import __version__
from a2a_mcp_server.gateway_client import GatewayClient, GatewayError
from a2a_mcp_server.tool_discovery import catalog_to_mcp_tools

_CATALOG_TTL_SECONDS = 10.0


def build_server(client: GatewayClient) -> Server:
    """Create a configured MCP ``Server`` wired to the gateway client."""
    server: Server = Server(name="a2a-mcp-server", version=__version__)
    cache: dict[str, Any] = {"expires": 0.0, "tools": []}

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        now = time.monotonic()
        if cache["tools"] and cache["expires"] > now:
            return cache["tools"]
        catalog = await client.list_tools()
        tools = catalog_to_mcp_tools(catalog)
        cache["tools"] = tools
        cache["expires"] = now + _CATALOG_TTL_SECONDS
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        try:
            result = await client.invoke_tool(name, arguments or {})
        except GatewayError as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]
        payload = json.dumps(result, default=str)
        return [TextContent(type="text", text=payload)]

    return server
