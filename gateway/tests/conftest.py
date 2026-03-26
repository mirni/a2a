"""Shared fixtures for gateway tests.

Uses httpx AsyncClient with Starlette's ASGI transport — no real server needed.
Lifespan is managed manually since httpx.ASGITransport does not handle it.
"""

from __future__ import annotations

import os
import sys

import pytest

# Ensure project root is on sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Bootstrap product imports before anything else
import gateway.src.bootstrap  # noqa: F401

import httpx

from gateway.src.app import create_app
from gateway.src.lifespan import lifespan


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for all databases."""
    return str(tmp_path)


@pytest.fixture
async def app(tmp_data_dir, monkeypatch):
    """Create a Starlette app with lifespan managed."""
    monkeypatch.setenv("A2A_DATA_DIR", tmp_data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{tmp_data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{tmp_data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{tmp_data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{tmp_data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{tmp_data_dir}/trust.db")

    application = create_app()

    # Manually run the lifespan
    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    yield application
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def client(app):
    """Provide an httpx AsyncClient connected to the test app via ASGI transport."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def api_key(app, client):
    """Create an API key and return it.

    Also creates a wallet with 1000 credits for the test agent.
    """
    ctx = app.state.ctx

    # Create a wallet with credits
    await ctx.tracker.wallet.create("test-agent", initial_balance=1000.0)

    # Create an API key
    key_info = await ctx.key_manager.create_key("test-agent", tier="free")
    return key_info["key"]


@pytest.fixture
async def pro_api_key(app, client):
    """Create a pro-tier API key with a funded wallet."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("pro-agent", initial_balance=5000.0)
    key_info = await ctx.key_manager.create_key("pro-agent", tier="pro")
    return key_info["key"]
