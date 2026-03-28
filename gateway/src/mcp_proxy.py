"""MCP connector proxy — spawns MCP stdio servers and proxies tool calls.

Supports three connector types:
- stripe: @stripe/mcp (npx) or built-in connector
- github: products/connectors/github MCP server
- postgres: products/connectors/postgres MCP server

Each connector is lazy-started on first use and kept alive for the gateway's lifetime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("a2a.mcp_proxy")

# Tool definitions for each connector (added to catalog dynamically)
STRIPE_MCP_TOOLS = [
    "stripe_list_customers", "stripe_create_customer",
    "stripe_list_products", "stripe_create_product",
    "stripe_list_prices", "stripe_create_price",
    "stripe_create_payment_link",
    "stripe_list_invoices", "stripe_create_invoice",
    "stripe_list_subscriptions", "stripe_cancel_subscription",
    "stripe_create_refund",
    "stripe_retrieve_balance",
]

GITHUB_MCP_TOOLS = [
    "github_list_repos", "github_get_repo",
    "github_list_issues", "github_create_issue",
    "github_list_pull_requests", "github_get_pull_request",
    "github_create_pull_request",
    "github_list_commits", "github_get_file_contents",
    "github_search_code",
]

POSTGRES_MCP_TOOLS = [
    "pg_query", "pg_execute", "pg_list_tables",
    "pg_describe_table", "pg_explain_query", "pg_list_schemas",
]

# Map gateway tool name → (connector, mcp_tool_name)
_TOOL_MAP: dict[str, tuple[str, str]] = {}
for t in STRIPE_MCP_TOOLS:
    _TOOL_MAP[t] = ("stripe", t.replace("stripe_", "", 1))
for t in GITHUB_MCP_TOOLS:
    _TOOL_MAP[t] = ("github", t.replace("github_", "", 1))
for t in POSTGRES_MCP_TOOLS:
    _TOOL_MAP[t] = ("postgres", t.replace("pg_", "", 1))


@dataclass
class MCPConnection:
    """A running MCP stdio connection."""

    process: asyncio.subprocess.Process
    _id_counter: int = field(default=0, init=False)
    _pending: dict[int, asyncio.Future] = field(default_factory=dict, init=False)
    _reader_task: asyncio.Task | None = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)

    async def start(self) -> None:
        """Start reading responses from the MCP server."""
        self._reader_task = asyncio.create_task(self._read_loop())
        await self._initialize()

    async def _initialize(self) -> None:
        """Send MCP initialize handshake."""
        resp = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "a2a-gateway", "version": "0.1.0"},
        })
        # Send initialized notification
        await self._send_notification("notifications/initialized", {})
        self._initialized = True
        logger.info("MCP connection initialized: %s", resp.get("serverInfo", {}).get("name", "?"))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # Extract text content from MCP result
        content = result.get("content", [])
        if content and isinstance(content, list):
            text = content[0].get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"text": text}
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and wait for response."""
        self._id_counter += 1
        req_id = self._id_counter
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        data = json.dumps(msg) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"MCP request timed out: {method}")

    async def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        data = json.dumps(msg) + "\n"
        self.process.stdin.write(data.encode())
        await self.process.stdin.drain()

    async def _read_loop(self) -> None:
        """Read JSON-RPC responses from stdout."""
        assert self.process.stdout is not None
        buffer = b""
        while True:
            try:
                chunk = await self.process.stdout.read(8192)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    req_id = msg.get("id")
                    if req_id is not None and req_id in self._pending:
                        future = self._pending.pop(req_id)
                        if "error" in msg:
                            future.set_exception(
                                RuntimeError(f"MCP error: {msg['error']}")
                            )
                        else:
                            future.set_result(msg.get("result", {}))
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in MCP read loop")
                break

    async def close(self) -> None:
        """Terminate the MCP server process."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()


class MCPProxyManager:
    """Manages MCP connector subprocesses and proxies tool calls."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}
        self._locks: dict[str, asyncio.Lock] = {
            "stripe": asyncio.Lock(),
            "github": asyncio.Lock(),
            "postgres": asyncio.Lock(),
        }

    def is_connector_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to a connector."""
        return tool_name in _TOOL_MAP

    def get_connector_tools(self) -> list[str]:
        """Get all connector tool names."""
        return list(_TOOL_MAP.keys())

    async def call_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a connector tool, lazily starting the connector if needed."""
        if tool_name not in _TOOL_MAP:
            raise ValueError(f"Unknown connector tool: {tool_name}")

        connector_name, mcp_tool_name = _TOOL_MAP[tool_name]
        conn = await self._ensure_connection(connector_name)
        return await conn.call_tool(mcp_tool_name, params)

    async def _ensure_connection(self, connector: str) -> MCPConnection:
        """Get or create an MCP connection for the given connector."""
        if connector in self._connections:
            conn = self._connections[connector]
            if conn.process.returncode is None:
                return conn
            # Process died, remove it
            del self._connections[connector]

        async with self._locks[connector]:
            # Double-check after acquiring lock
            if connector in self._connections:
                return self._connections[connector]

            conn = await self._start_connector(connector)
            self._connections[connector] = conn
            return conn

    async def _start_connector(self, connector: str) -> MCPConnection:
        """Start an MCP connector subprocess."""
        if connector == "stripe":
            return await self._start_stripe()
        elif connector == "github":
            return await self._start_python_connector("github")
        elif connector == "postgres":
            return await self._start_python_connector("postgres")
        else:
            raise ValueError(f"Unknown connector: {connector}")

    async def _start_stripe(self) -> MCPConnection:
        """Start the @stripe/mcp server via npx."""
        stripe_key = os.environ.get("STRIPE_API_KEY", "")
        if not stripe_key:
            raise ValueError("STRIPE_API_KEY not configured")

        npx = shutil.which("npx")
        if not npx:
            raise RuntimeError("npx not found — install Node.js to use Stripe MCP connector")

        env = {**os.environ, "STRIPE_SECRET_KEY": stripe_key}
        process = await asyncio.create_subprocess_exec(
            npx, "-y", "@stripe/mcp@latest", "--tools=all",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        logger.info("Started Stripe MCP server (pid=%d)", process.pid)
        conn = MCPConnection(process=process)
        await conn.start()
        return conn

    async def _start_python_connector(self, name: str) -> MCPConnection:
        """Start a Python MCP connector as subprocess."""
        install_dir = os.environ.get("A2A_INSTALL_DIR", "/opt/a2a")
        connector_dir = os.path.join(install_dir, "products", "connectors", name)

        if not os.path.isdir(connector_dir):
            # Try relative path from gateway
            connector_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "..", "products", "connectors", name)
            )

        python = sys.executable
        process = await asyncio.create_subprocess_exec(
            python, "-m", "src.server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=connector_dir,
            env=os.environ.copy(),
        )
        logger.info("Started %s MCP server (pid=%d)", name, process.pid)
        conn = MCPConnection(process=process)
        await conn.start()
        return conn

    async def close(self) -> None:
        """Shut down all MCP connections."""
        for name, conn in self._connections.items():
            logger.info("Stopping %s MCP server", name)
            await conn.close()
        self._connections.clear()
