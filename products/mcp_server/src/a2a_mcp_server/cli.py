"""Command-line entry point for a2a-mcp-server.

Usage::

    a2a-mcp-server                    # stdio transport (default)
    a2a-mcp-server --transport stdio
    a2a-mcp-server --transport http --host 0.0.0.0 --port 8765

Environment variables:
    A2A_API_KEY      API key (required)
    A2A_BASE_URL     Gateway base URL (default: https://api.greenhelix.net)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from a2a_mcp_server._version import __version__
from a2a_mcp_server.gateway_client import GatewayClient
from a2a_mcp_server.server import build_server

logger = logging.getLogger("a2a_mcp_server")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="a2a-mcp-server",
        description="MCP server exposing the A2A Commerce Gateway's 141 tools.",
    )
    parser.add_argument("--version", action="version", version=f"a2a-mcp-server {__version__}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("A2A_MCP_TRANSPORT", "stdio"),
        help="MCP transport to serve on (default: stdio).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("A2A_BASE_URL", "https://api.greenhelix.net"),
        help="A2A gateway base URL (default: https://api.greenhelix.net).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("A2A_API_KEY"),
        help="A2A gateway API key (overrides A2A_API_KEY env var).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("A2A_MCP_HOST", "127.0.0.1"),
        help="HTTP transport host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("A2A_MCP_PORT", "8765")),
        help="HTTP transport port (default: 8765).",
    )
    return parser.parse_args(argv)


async def _run_stdio(args: argparse.Namespace) -> int:
    from mcp.server.stdio import stdio_server

    if not args.api_key:
        print(
            "ERROR: A2A_API_KEY is required. Set the env var or pass --api-key.",
            file=sys.stderr,
        )
        return 2

    async with GatewayClient(base_url=args.base_url, api_key=args.api_key) as client:
        server = build_server(client)
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    return 0


async def _run_http(args: argparse.Namespace) -> int:
    """Run the server over Streamable HTTP transport.

    The MCP SDK ships a Starlette-based ASGI handler; we mount it on a
    minimal app and serve it with uvicorn.
    """
    if not args.api_key:
        print(
            "ERROR: A2A_API_KEY is required. Set the env var or pass --api-key.",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount
    except ImportError as exc:
        print(
            f"ERROR: HTTP transport requires extras: pip install 'a2a-mcp-server[http]'\n{exc}",
            file=sys.stderr,
        )
        return 2

    async with GatewayClient(base_url=args.base_url, api_key=args.api_key) as client:
        server = build_server(client)
        session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

        async def handle_mcp(scope, receive, send):
            await session_manager.handle_request(scope, receive, send)

        app = Starlette(routes=[Mount("/mcp", app=handle_mcp)])
        async with session_manager.run():
            config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
            await uvicorn.Server(config).serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    if args.transport == "stdio":
        return asyncio.run(_run_stdio(args))
    return asyncio.run(_run_http(args))


if __name__ == "__main__":
    raise SystemExit(main())
