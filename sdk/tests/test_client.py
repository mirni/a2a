"""Tests for the A2A SDK client.

Uses the gateway's ASGI transport — no real server needed.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure project root is on sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Bootstrap product imports
import gateway.src.bootstrap  # noqa: F401

import httpx

from gateway.src.app import create_app
from gateway.src.lifespan import lifespan
from sdk.src.a2a_client import A2AClient
from sdk.src.a2a_client.errors import (
    AuthenticationError,
    InsufficientTierError,
    ToolNotFoundError,
)


@pytest.fixture
async def gateway_app(tmp_path, monkeypatch):
    data_dir = str(tmp_path)
    monkeypatch.setenv("A2A_DATA_DIR", data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")

    app = create_app()
    ctx_manager = lifespan(app)
    await ctx_manager.__aenter__()
    yield app
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def sdk_client(gateway_app):
    """A2AClient wired to the test gateway via ASGI transport."""
    transport = httpx.ASGITransport(app=gateway_app)
    client = A2AClient.__new__(A2AClient)
    client.base_url = "http://test"
    client.api_key = None
    client._client = httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    )
    yield client
    await client.close()


@pytest.fixture
async def setup_agent(gateway_app, sdk_client):
    """Set up a test agent with wallet and API key, return the key."""
    ctx = gateway_app.state.ctx
    await ctx.tracker.wallet.create("sdk-agent", initial_balance=1000.0)
    key_info = await ctx.key_manager.create_key("sdk-agent", tier="free")
    sdk_client.api_key = key_info["key"]
    return key_info["key"]


@pytest.mark.asyncio
async def test_health(sdk_client):
    health = await sdk_client.health()
    assert health.status == "ok"
    assert health.version == "0.1.0"
    assert health.tools > 0


@pytest.mark.asyncio
async def test_pricing(sdk_client):
    tools = await sdk_client.pricing()
    assert len(tools) > 0
    assert tools[0].name
    assert tools[0].service


@pytest.mark.asyncio
async def test_pricing_tool(sdk_client):
    tool = await sdk_client.pricing_tool("get_balance")
    assert tool.name == "get_balance"
    assert tool.service == "billing"


@pytest.mark.asyncio
async def test_pricing_tool_not_found(sdk_client):
    with pytest.raises(ToolNotFoundError):
        await sdk_client.pricing_tool("nonexistent")


@pytest.mark.asyncio
async def test_get_balance(sdk_client, setup_agent):
    balance = await sdk_client.get_balance("sdk-agent")
    assert balance == 1000.0


@pytest.mark.asyncio
async def test_deposit(sdk_client, setup_agent):
    new_balance = await sdk_client.deposit("sdk-agent", 100.0)
    assert new_balance == 1100.0


@pytest.mark.asyncio
async def test_get_usage_summary(sdk_client, setup_agent):
    summary = await sdk_client.get_usage_summary("sdk-agent")
    assert "total_cost" in summary
    assert "total_calls" in summary


@pytest.mark.asyncio
async def test_authentication_error(sdk_client):
    sdk_client.api_key = "invalid_key_12345"
    with pytest.raises(AuthenticationError):
        await sdk_client.get_balance("anyone")


@pytest.mark.asyncio
async def test_search_services(sdk_client, setup_agent):
    services = await sdk_client.search_services(query="test")
    assert isinstance(services, list)


@pytest.mark.asyncio
async def test_insufficient_tier(sdk_client, setup_agent):
    """Free tier cannot use pro tools like create_escrow."""
    with pytest.raises(InsufficientTierError):
        await sdk_client.create_escrow("sdk-agent", "payee", 10.0)


@pytest.mark.asyncio
async def test_create_payment_intent(sdk_client, setup_agent, gateway_app):
    ctx = gateway_app.state.ctx
    await ctx.tracker.wallet.create("payee-sdk", initial_balance=0.0)

    intent = await sdk_client.create_payment_intent(
        payer="sdk-agent", payee="payee-sdk", amount=10.0, description="sdk test"
    )
    assert intent["status"] == "pending"
    assert intent["amount"] == 10.0

    # Capture it
    settlement = await sdk_client.capture_payment(intent["id"])
    assert settlement["status"] == "settled"
