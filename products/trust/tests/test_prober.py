"""Tests for the MCP server health prober."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from src.models import Server, TransportType
from src.prober import Prober
from src.storage import StorageBackend


@dataclass
class MockMCPTransport:
    """Mock transport that returns configurable responses."""

    tools: list[dict[str, Any]] | None = None
    error: str | None = None
    status_code: int = 200
    latency_ms: float = 50.0
    raise_exception: Exception | None = None

    async def list_tools(self, url: str) -> dict[str, Any]:
        if self.raise_exception:
            raise self.raise_exception

        if self.tools is not None:
            tools = self.tools
        else:
            tools = [
                {"name": "tool1", "description": "A test tool", "parameters": {}},
                {"name": "tool2", "description": "Another tool", "parameters": {}},
                {"name": "tool3", "description": "", "parameters": {}},  # undocumented
            ]
        return {
            "status_code": self.status_code,
            "tools": tools,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }

    async def call_tool(self, url: str, tool_name: str, args: dict) -> dict[str, Any]:
        return {"status_code": 200, "latency_ms": self.latency_ms}


class TestProber:
    async def test_successful_probe(self, storage, sample_server):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        result = await prober.probe(sample_server.id, sample_server.url)

        assert result.server_id == sample_server.id
        assert result.status_code == 200
        assert result.error is None
        assert result.tools_count == 3
        assert result.tools_documented == 2  # tool3 has empty description
        assert result.latency_ms == 50.0

    async def test_probe_stores_result(self, storage, sample_server):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        await prober.probe(sample_server.id, sample_server.url)

        stored = await storage.get_probe_results(sample_server.id)
        assert len(stored) == 1
        assert stored[0].tools_count == 3

    async def test_probe_updates_last_probed(self, storage, sample_server):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        before = time.time()
        await prober.probe(sample_server.id, sample_server.url)

        server = await storage.get_server(sample_server.id)
        assert server is not None
        assert server.last_probed_at is not None
        assert server.last_probed_at >= before

    async def test_probe_with_error_response(self, storage, sample_server):
        transport = MockMCPTransport(status_code=500, error="Internal error")
        prober = Prober(storage=storage, transport=transport)

        result = await prober.probe(sample_server.id, sample_server.url)

        assert result.status_code == 500
        assert result.error == "Internal error"

    async def test_probe_with_exception(self, storage, sample_server):
        transport = MockMCPTransport(raise_exception=ConnectionError("Connection refused"))
        prober = Prober(storage=storage, transport=transport)

        result = await prober.probe(sample_server.id, sample_server.url)

        assert result.status_code == 500
        assert "Connection refused" in result.error
        assert result.tools_count == 0

    async def test_probe_with_no_tools(self, storage, sample_server):
        transport = MockMCPTransport(tools=[])
        prober = Prober(storage=storage, transport=transport)

        result = await prober.probe(sample_server.id, sample_server.url)

        assert result.tools_count == 0
        assert result.tools_documented == 0

    async def test_probe_server_by_id(self, storage, sample_server):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        result = await prober.probe_server(sample_server.id)

        assert result.server_id == sample_server.id
        assert result.status_code == 200

    async def test_probe_server_not_found(self, storage):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        with pytest.raises(ValueError, match="Server not found"):
            await prober.probe_server("nonexistent-id")

    async def test_multiple_probes(self, storage, sample_server):
        transport = MockMCPTransport()
        prober = Prober(storage=storage, transport=transport)

        for _ in range(5):
            await prober.probe(sample_server.id, sample_server.url)

        results = await storage.get_probe_results(sample_server.id)
        assert len(results) == 5
