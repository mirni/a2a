"""Tests for the MCP server surfacing gatekeeper tools.

The gatekeeper tools (``submit_verification``, ``get_verification_status``,
``list_verification_jobs``, ``cancel_verification``, ``get_proof``,
``verify_proof``) are registered in the gateway's tool catalog and served
via ``GET /v1/pricing``. The MCP server is fully dynamic — it proxies
whatever tools the gateway exposes — so these tests verify end-to-end that:

1. The MCP ``tools/list`` handler exposes the six gatekeeper tools.
2. Tool descriptions correctly surface ``tier=pro`` so planner LLMs can
   route around unaffordable calls.
3. The MCP ``tools/call`` handler can submit a verification and fetch
   its status through the real gateway.

The tests spin up the full gateway via httpx.ASGITransport and point the
MCP ``GatewayClient`` at it, so nothing is mocked above the transport
layer.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
import pytest

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import gateway.src.bootstrap  # noqa: F401
from a2a_mcp_server.gateway_client import GatewayClient
from a2a_mcp_server.server import build_server
from gateway.src.app import create_app
from gateway.src.lifespan import lifespan

GATEKEEPER_TOOL_NAMES = {
    "submit_verification",
    "get_verification_status",
    "list_verification_jobs",
    "cancel_verification",
    "get_proof",
    "verify_proof",
}


@pytest.fixture
async def gateway_app(tmp_path, monkeypatch):
    data_dir = str(tmp_path)
    monkeypatch.setenv("A2A_DATA_DIR", data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db")

    app = create_app()
    ctx_manager = lifespan(app)
    await ctx_manager.__aenter__()
    yield app
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def pro_api_key(gateway_app):
    ctx = gateway_app.state.ctx
    await ctx.tracker.wallet.create("mcp-verifier-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("mcp-verifier-agent", tier="pro")
    return key_info["key"]


@pytest.fixture
async def mcp_gateway_client(gateway_app, pro_api_key):
    transport = httpx.ASGITransport(app=gateway_app)
    client = GatewayClient(
        base_url="http://test",
        api_key=pro_api_key,
        transport=transport,
    )
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_mcp_list_tools_includes_gatekeeper(mcp_gateway_client):
    """``tools/list`` exposes all six gatekeeper tools from the catalog."""
    server = build_server(mcp_gateway_client)
    tools = await _call_list_tools(server)
    names = {t.name for t in tools}
    missing = GATEKEEPER_TOOL_NAMES - names
    assert not missing, f"missing gatekeeper tools: {missing}"


@pytest.mark.asyncio
async def test_mcp_gatekeeper_tools_surface_pro_tier(mcp_gateway_client):
    """Tier hints belong in the description so planner LLMs can route."""
    server = build_server(mcp_gateway_client)
    tools = await _call_list_tools(server)
    paid = [t for t in tools if t.name in {"submit_verification", "get_verification_status"}]
    assert paid, "expected pro-tier gatekeeper tools in catalog"
    for tool in paid:
        assert "pro" in tool.description.lower(), (
            f"{tool.name} description missing pro tier hint: {tool.description!r}"
        )


@pytest.mark.asyncio
async def test_mcp_submit_verification_end_to_end(mcp_gateway_client):
    """An MCP ``tools/call`` for submit_verification hits the real gateway."""
    server = build_server(mcp_gateway_client)
    content = await _call_tool(
        server,
        "submit_verification",
        {
            "agent_id": "mcp-verifier-agent",
            "properties": [
                {
                    "name": "x_in_range",
                    "language": "json_policy",
                    "expression": json.dumps(
                        {
                            "name": "x_in_range",
                            "variables": [{"name": "x", "type": "int", "value": 5}],
                            "assertions": [
                                {"op": ">", "args": ["x", 0]},
                                {"op": "<", "args": ["x", 10]},
                            ],
                        }
                    ),
                }
            ],
        },
    )
    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert "error" not in payload, payload
    assert payload["job_id"].startswith("vj-")


@pytest.mark.asyncio
async def test_mcp_get_verification_status_after_submit(mcp_gateway_client):
    """After an MCP-submitted job we can fetch its status via MCP too."""
    server = build_server(mcp_gateway_client)
    submit_content = await _call_tool(
        server,
        "submit_verification",
        {
            "agent_id": "mcp-verifier-agent",
            "properties": [
                {
                    "name": "positive_x",
                    "language": "json_policy",
                    "expression": json.dumps(
                        {
                            "name": "positive_x",
                            "variables": [{"name": "x", "type": "int", "value": 7}],
                            "assertions": [{"op": ">", "args": ["x", 0]}],
                        }
                    ),
                }
            ],
        },
    )
    job_id = json.loads(submit_content[0].text)["job_id"]

    status_content = await _call_tool(server, "get_verification_status", {"job_id": job_id})
    status_payload = json.loads(status_content[0].text)
    assert status_payload["job_id"] == job_id
    assert status_payload["status"] in {"pending", "completed", "failed", "timeout"}
    assert status_payload.get("result") == "satisfied"


# ---------------------------------------------------------------------------
# Helpers that invoke the MCP low-level Server handlers directly.
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
