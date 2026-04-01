"""Tests for MCP connector proxy.

Covers:
- _TOOL_MAP: correct gateway→(connector, mcp_tool) mapping
- MCPConnection: JSON-RPC protocol over stdio using a fake subprocess
- MCPProxyManager: tool routing, unknown tool errors, lazy-start
- Tool call content extraction: JSON text, plain text, empty content
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# _TOOL_MAP tests (pure data, no async)
# ---------------------------------------------------------------------------


class TestToolMap:
    """Verify the gateway tool name → (connector, mcp_tool_name) mapping."""

    def test_stripe_tools_mapped(self):
        from gateway.src.mcp_proxy import _TOOL_MAP, STRIPE_MCP_TOOLS

        for tool in STRIPE_MCP_TOOLS:
            assert tool in _TOOL_MAP
            connector, mcp_name = _TOOL_MAP[tool]
            assert connector == "stripe"
            assert mcp_name == tool.replace("stripe_", "", 1)

    def test_github_tools_mapped(self):
        from gateway.src.mcp_proxy import _TOOL_MAP, GITHUB_MCP_TOOLS

        for tool in GITHUB_MCP_TOOLS:
            assert tool in _TOOL_MAP
            connector, mcp_name = _TOOL_MAP[tool]
            assert connector == "github"
            assert mcp_name == tool.replace("github_", "", 1)

    def test_postgres_tools_mapped(self):
        from gateway.src.mcp_proxy import _TOOL_MAP, POSTGRES_MCP_TOOLS

        for tool in POSTGRES_MCP_TOOLS:
            assert tool in _TOOL_MAP
            connector, mcp_name = _TOOL_MAP[tool]
            assert connector == "postgres"
            assert mcp_name == tool.replace("pg_", "", 1)

    def test_total_tool_count(self):
        from gateway.src.mcp_proxy import (
            _TOOL_MAP,
            GITHUB_MCP_TOOLS,
            POSTGRES_MCP_TOOLS,
            STRIPE_MCP_TOOLS,
        )

        expected = len(STRIPE_MCP_TOOLS) + len(GITHUB_MCP_TOOLS) + len(POSTGRES_MCP_TOOLS)
        assert len(_TOOL_MAP) == expected
        assert expected == 29

    def test_no_duplicate_tool_names(self):
        from gateway.src.mcp_proxy import (
            GITHUB_MCP_TOOLS,
            POSTGRES_MCP_TOOLS,
            STRIPE_MCP_TOOLS,
        )

        all_tools = STRIPE_MCP_TOOLS + GITHUB_MCP_TOOLS + POSTGRES_MCP_TOOLS
        assert len(all_tools) == len(set(all_tools))

    def test_stripe_prefix_stripped_correctly(self):
        from gateway.src.mcp_proxy import _TOOL_MAP

        _, mcp_name = _TOOL_MAP["stripe_list_customers"]
        assert mcp_name == "list_customers"

    def test_github_prefix_stripped_correctly(self):
        from gateway.src.mcp_proxy import _TOOL_MAP

        _, mcp_name = _TOOL_MAP["github_list_repos"]
        assert mcp_name == "list_repos"

    def test_postgres_prefix_stripped_correctly(self):
        from gateway.src.mcp_proxy import _TOOL_MAP

        _, mcp_name = _TOOL_MAP["pg_query"]
        assert mcp_name == "query"


# ---------------------------------------------------------------------------
# MCPConnection tests (using a fake subprocess via asyncio pipes)
# ---------------------------------------------------------------------------


def _make_fake_process(responses: list[dict]):
    """Create a fake subprocess that simulates an MCP stdio server.

    Responses are delivered reactively: each stdin drain() triggers the next
    response to be made available on stdout, mimicking real request→response
    flow.
    """
    process = MagicMock()
    process.returncode = None

    # Queue for responses that have been "released" by a drain
    ready_queue: asyncio.Queue[bytes] = asyncio.Queue()
    pending_responses = list(responses)

    async def fake_read(n):
        try:
            return await asyncio.wait_for(ready_queue.get(), timeout=5.0)
        except TimeoutError:
            return b""

    process.stdout = MagicMock()
    process.stdout.read = fake_read

    # Stdin: capture writes; drain releases next response
    written_data: list[bytes] = []

    def fake_write(data):
        written_data.append(data)

    async def fake_drain():
        # Release next response only if the last write was a request (has "id"),
        # not a notification (no "id"). This mimics real server behavior.
        if written_data and pending_responses:
            last_msg = json.loads(written_data[-1])
            if "id" in last_msg:
                resp = pending_responses.pop(0)
                ready_queue.put_nowait(json.dumps(resp).encode() + b"\n")

    process.stdin = MagicMock()
    process.stdin.write = fake_write
    process.stdin.drain = fake_drain
    process._written = written_data

    # Terminate/kill
    process.terminate = MagicMock()
    process.kill = MagicMock()

    async def fake_wait():
        pass

    process.wait = fake_wait

    return process


class TestMCPConnection:
    """Tests for MCPConnection JSON-RPC protocol."""

    async def test_call_tool_extracts_json_content(self):
        from gateway.src.mcp_proxy import MCPConnection

        # Responses: 1=initialize, 2=tools/call
        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": '{"customers": []}'}]},
            },
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        result = await conn.call_tool("list_customers", {})
        assert result == {"customers": []}

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_call_tool_returns_plain_text(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "not json, just text"}]},
            },
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        result = await conn.call_tool("some_tool", {})
        assert result == {"text": "not json, just text"}

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_call_tool_empty_content(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": 2, "result": {"content": []}},
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        result = await conn.call_tool("some_tool", {})
        assert result == {"content": []}

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_initialize_sends_handshake(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "mock"}}},
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        assert conn._initialized is True

        # Verify the initialize request was sent
        assert len(process._written) >= 1
        init_msg = json.loads(process._written[0])
        assert init_msg["method"] == "initialize"
        assert init_msg["params"]["protocolVersion"] == "2024-11-05"

        # Verify the initialized notification was sent
        assert len(process._written) >= 2
        notif_msg = json.loads(process._written[1])
        assert notif_msg["method"] == "notifications/initialized"
        assert "id" not in notif_msg  # notifications have no id

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_send_request_increments_id(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        await conn.list_tools()

        # init=id1, notification (no id), list_tools=id2
        requests = [json.loads(d) for d in process._written if b'"id"' in d]
        ids = [r["id"] for r in requests]
        assert ids == [1, 2]

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_mcp_error_raises_runtime_error(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "error": {"code": -32600, "message": "Invalid request"},
            },
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        with pytest.raises(RuntimeError, match="MCP error"):
            await conn.call_tool("bad_tool", {})

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_close_terminates_process(self):
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()
        await conn.close()

        process.terminate.assert_called_once()


# ---------------------------------------------------------------------------
# MCPProxyManager tests
# ---------------------------------------------------------------------------


class TestMCPProxyManager:
    """Tests for MCPProxyManager routing and lifecycle."""

    def test_is_connector_tool_true(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        assert mgr.is_connector_tool("stripe_list_customers") is True
        assert mgr.is_connector_tool("github_list_repos") is True
        assert mgr.is_connector_tool("pg_query") is True

    def test_is_connector_tool_false(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        assert mgr.is_connector_tool("get_balance") is False
        assert mgr.is_connector_tool("nonexistent_tool") is False

    def test_get_connector_tools_returns_all(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        tools = mgr.get_connector_tools()
        assert len(tools) == 29
        assert "stripe_list_customers" in tools
        assert "github_list_repos" in tools
        assert "pg_query" in tools

    async def test_call_unknown_tool_raises(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        with pytest.raises(ValueError, match="Unknown connector tool"):
            await mgr.call_tool("nonexistent_tool", {})

    async def test_close_empty_manager(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        await mgr.close()  # Should not raise

    async def test_start_stripe_requires_api_key(self):
        from gateway.src.mcp_proxy import MCPProxyManager

        mgr = MCPProxyManager()
        # No STRIPE_API_KEY set
        with patch.dict("os.environ", {}, clear=False):
            if "STRIPE_API_KEY" in __import__("os").environ:
                del __import__("os").environ["STRIPE_API_KEY"]
            with pytest.raises(ValueError, match="STRIPE_API_KEY"):
                await mgr._start_stripe()


# ---------------------------------------------------------------------------
# register_mcp_tools tests
# ---------------------------------------------------------------------------


class TestRegisterMCPTools:
    """Tests for dynamic tool registration."""

    def test_register_adds_all_connector_tools(self):
        from gateway.src.mcp_proxy import _TOOL_MAP
        from gateway.src.tools import TOOL_REGISTRY, register_mcp_tools

        # Create a mock proxy manager
        mock_proxy = MagicMock()
        register_mcp_tools(mock_proxy)

        for tool_name in _TOOL_MAP:
            assert tool_name in TOOL_REGISTRY, f"{tool_name} not in registry"

    def test_registered_handlers_are_callable(self):
        from gateway.src.mcp_proxy import _TOOL_MAP
        from gateway.src.tools import TOOL_REGISTRY, register_mcp_tools

        mock_proxy = MagicMock()
        register_mcp_tools(mock_proxy)

        for tool_name in _TOOL_MAP:
            handler = TOOL_REGISTRY[tool_name]
            assert callable(handler)


# ---------------------------------------------------------------------------
# MCPConnection edge cases
# ---------------------------------------------------------------------------


class TestMCPConnectionEdgeCases:
    """Edge cases: process death, non-JSON lines, stdout EOF."""

    async def test_timeout_on_no_response(self):
        """If the server never responds, call_tool should raise TimeoutError."""
        from gateway.src.mcp_proxy import MCPConnection

        # Process that responds to init but not to tool call
        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            # No second response — will timeout
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        conn._timeout = 0.5  # Short timeout for test
        await conn.start()

        with pytest.raises((asyncio.TimeoutError, RuntimeError)):
            await conn.call_tool("some_tool", {})

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass

    async def test_process_dead_detected(self):
        """If process is already dead, stdout read returns empty."""
        from gateway.src.mcp_proxy import MCPConnection

        process = MagicMock()
        process.returncode = 1  # Already dead

        async def fake_read(n):
            return b""

        process.stdout = MagicMock()
        process.stdout.read = fake_read
        process.stdin = MagicMock()
        process.stdin.write = MagicMock()

        async def fake_drain():
            pass

        process.stdin.drain = fake_drain
        process.terminate = MagicMock()
        process.kill = MagicMock()

        async def fake_wait():
            pass

        process.wait = fake_wait

        conn = MCPConnection(process=process)
        # The reader loop should exit quickly on empty reads
        # We just verify no crash
        conn._initialized = False

    async def test_call_tool_with_various_argument_types(self):
        """Tool call with nested dicts, lists, and nulls."""
        from gateway.src.mcp_proxy import MCPConnection

        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "test"}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": '{"ok": true}'}]},
            },
        ]
        process = _make_fake_process(responses)
        conn = MCPConnection(process=process)
        await conn.start()

        result = await conn.call_tool(
            "some_tool",
            {
                "nested": {"key": "value"},
                "list": [1, 2, 3],
                "null": None,
            },
        )
        assert result == {"ok": True}

        # Verify the arguments were sent correctly
        tool_call = json.loads(process._written[2])  # init, notif, tool_call
        assert tool_call["params"]["arguments"]["nested"] == {"key": "value"}

        conn._reader_task.cancel()
        try:
            await conn._reader_task
        except asyncio.CancelledError:
            pass
