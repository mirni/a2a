"""a2a-mcp-server — MCP server exposing the A2A Commerce Gateway's 141 tools.

This package wraps https://api.greenhelix.net (or a self-hosted gateway)
behind the Model Context Protocol, so any MCP-aware client (Claude Desktop,
Cursor, Claude Code, Windsurf, ...) can discover and invoke agent-commerce
tools — billing, payments, escrow, identity, marketplace, trust — directly.
"""

from __future__ import annotations

from a2a_mcp_server._version import __version__
from a2a_mcp_server.gateway_client import (
    GatewayAuthError,
    GatewayClient,
    GatewayError,
    GatewayRateLimitError,
)
from a2a_mcp_server.server import build_server
from a2a_mcp_server.tool_discovery import catalog_to_mcp_tools

__all__ = [
    "__version__",
    "GatewayClient",
    "GatewayError",
    "GatewayAuthError",
    "GatewayRateLimitError",
    "build_server",
    "catalog_to_mcp_tools",
]
