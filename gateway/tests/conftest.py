"""Shared fixtures for gateway tests.

Uses httpx AsyncClient with FastAPI's ASGI transport — no real server needed.
Lifespan is managed manually since httpx.ASGITransport does not handle it.
"""

from __future__ import annotations

import os
import sys

import pytest

# Allow existing tests to use /v1/execute for all tools (legacy mode).
# New tests in test_execute_deprecation.py explicitly unset this.
os.environ["A2A_LEGACY_EXECUTE"] = "1"

# Ensure project root is on sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Bootstrap product imports before anything else
import httpx

import gateway.src.bootstrap  # noqa: F401
from gateway.src.app import create_app
from gateway.src.lifespan import lifespan
from gateway.src.routes.sse import SSEConfig


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for all databases."""
    return str(tmp_path)


@pytest.fixture
async def app(tmp_data_dir, monkeypatch):
    """Create a FastAPI app with lifespan managed."""
    monkeypatch.setenv("A2A_DATA_DIR", tmp_data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{tmp_data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{tmp_data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{tmp_data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{tmp_data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{tmp_data_dir}/trust.db")
    monkeypatch.setenv("IDENTITY_DSN", f"sqlite:///{tmp_data_dir}/identity.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{tmp_data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{tmp_data_dir}/webhooks.db")
    monkeypatch.setenv("DISPUTE_DSN", f"sqlite:///{tmp_data_dir}/disputes.db")
    monkeypatch.setenv("MESSAGING_DSN", f"sqlite:///{tmp_data_dir}/messaging.db")

    application = create_app()

    # Use fast SSE config in tests so streaming endpoints terminate quickly.
    # Without this, the default 3600s max_connection_seconds would cause
    # httpx ASGI transport to hang waiting for the generator to finish.
    application.state.sse_config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.3,
    )

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
    await ctx.tracker.wallet.create("test-agent", initial_balance=1000.0, signup_bonus=False)

    # Create an API key
    key_info = await ctx.key_manager.create_key("test-agent", tier="free")
    return key_info["key"]


@pytest.fixture
async def pro_api_key(app, client):
    """Create a pro-tier API key with a funded wallet."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("pro-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("pro-agent", tier="pro")
    return key_info["key"]


@pytest.fixture
async def admin_api_key(app, client):
    """Create an admin-scoped pro-tier API key with a funded wallet.

    Admin scope is needed for admin-service tools like backup_database,
    restore_database, check_db_integrity, and list_backups.
    """
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("admin-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("admin-agent", tier="pro", scopes=["read", "write", "admin"])
    return key_info["key"]
