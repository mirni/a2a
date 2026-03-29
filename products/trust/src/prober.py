"""MCP server health prober.

Probes MCP servers to measure latency, error rates, tool availability,
and documentation quality. Designed to accept an injectable async callable
for testing against mock servers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from .models import ProbeResult
from .storage import StorageBackend


class MCPTransport(Protocol):
    """Protocol for MCP server communication.

    Implementations should connect to a server and return structured responses.
    In tests, inject a mock async callable that simulates MCP responses.
    """

    async def list_tools(self, url: str) -> dict[str, Any]:
        """Call list_tools on the server.

        Returns dict with:
          - status_code: int (200 for success)
          - tools: list of tool dicts with 'name', 'description', 'parameters'
          - error: optional error string
        """
        ...

    async def call_tool(self, url: str, tool_name: str, args: dict) -> dict[str, Any]:
        """Call a specific tool on the server.

        Returns dict with:
          - status_code: int
          - latency_ms: float
          - error: optional error string
        """
        ...


@dataclass
class Prober:
    """Health prober for MCP servers.

    Attributes:
        storage: StorageBackend for persisting results.
        transport: Async transport for communicating with MCP servers.
    """

    storage: StorageBackend
    transport: MCPTransport

    async def probe(self, server_id: str, url: str) -> ProbeResult:
        """Probe a single server and store the result.

        Measures:
        - Latency (time to complete list_tools call)
        - Status code (200 = OK, anything else = error)
        - Tool count and documentation coverage
        """
        start = time.time()
        try:
            response = await self.transport.list_tools(url)
            elapsed_ms = (time.time() - start) * 1000.0

            status_code = response.get("status_code", 200)
            error = response.get("error")
            tools = response.get("tools", [])
            tools_count = len(tools)
            tools_documented = sum(1 for t in tools if t.get("description") and len(t.get("description", "")) > 0)
            latency_ms = response.get("latency_ms", elapsed_ms)

        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000.0
            status_code = 500
            error = str(exc)
            tools_count = 0
            tools_documented = 0
            latency_ms = elapsed_ms

        now = time.time()
        result = ProbeResult(
            server_id=server_id,
            timestamp=now,
            latency_ms=latency_ms,
            status_code=status_code,
            error=error,
            tools_count=tools_count,
            tools_documented=tools_documented,
        )

        await self.storage.store_probe_result(result)
        await self.storage.update_server_last_probed(server_id, now)

        return result

    async def probe_server(self, server_id: str) -> ProbeResult:
        """Probe a server by looking up its URL from storage."""
        server = await self.storage.get_server(server_id)
        if server is None:
            raise ValueError(f"Server not found: {server_id}")
        return await self.probe(server_id, server.url)
