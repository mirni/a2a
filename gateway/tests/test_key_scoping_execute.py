"""Integration tests for API key scoping enforcement in POST /execute.

Tests that scope restrictions (allowed_tools, allowed_agent_ids, scopes,
expires_at) are enforced at the gateway level with appropriate HTTP status
codes and error messages.
"""

from __future__ import annotations

import time

import pytest


@pytest.fixture
async def scoped_read_key(app, client):
    """Create an API key with read-only scope and a funded wallet."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("scoped-read-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "scoped-read-agent",
        tier="free",
        scopes=["read"],
    )
    return key_info["key"]


@pytest.fixture
async def scoped_tool_key(app, client):
    """Create an API key restricted to get_balance tool only."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("scoped-tool-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "scoped-tool-agent",
        tier="free",
        allowed_tools=["get_balance"],
    )
    return key_info["key"]


@pytest.fixture
async def scoped_agent_key(app, client):
    """Create an API key restricted to operate on scoped-agent-caller only.

    The allowed_agent_ids restricts which agent_id param values are permitted.
    The caller's own agent_id is scoped-agent-caller, so it passes ownership.
    """
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("scoped-agent-caller", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "scoped-agent-caller",
        tier="free",
        allowed_agent_ids=["scoped-agent-caller"],
    )
    return key_info["key"]


@pytest.fixture
async def expired_key(app, client):
    """Create an expired API key."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("expired-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "expired-agent",
        tier="free",
        expires_at=time.time() - 60,  # expired 60s ago
    )
    return key_info["key"]


@pytest.fixture
async def admin_key(app, client):
    """Create an admin-scoped API key."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("admin-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "admin-agent",
        tier="pro",
        scopes=["read", "write", "admin"],
    )
    return key_info["key"]


# ---------------------------------------------------------------------------
# Expired key → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_key_returns_401(client, expired_key):
    """An expired key should be rejected with 401."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "expired-agent"}},
        headers={"Authorization": f"Bearer {expired_key}"},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Scope enforcement: read scope blocks write tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_scope_blocks_write_tool(client, scoped_read_key):
    """A key with only 'read' scope cannot call a 'write' tool (deposit)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "deposit", "params": {"agent_id": "scoped-read-agent", "amount": 10.0}},
        headers={"Authorization": f"Bearer {scoped_read_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/scope-violation")


@pytest.mark.asyncio
async def test_read_scope_allows_read_tool(client, scoped_read_key):
    """A key with 'read' scope can call a 'read' tool (get_balance)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "scoped-read-agent"}},
        headers={"Authorization": f"Bearer {scoped_read_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# allowed_tools enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_tools_blocks_unlisted_tool(client, scoped_tool_key):
    """A key restricted to get_balance cannot call get_usage_summary."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_usage_summary", "params": {"agent_id": "scoped-tool-agent"}},
        headers={"Authorization": f"Bearer {scoped_tool_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/scope-violation")


@pytest.mark.asyncio
async def test_allowed_tools_permits_listed_tool(client, scoped_tool_key):
    """A key restricted to get_balance can call get_balance."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "scoped-tool-agent"}},
        headers={"Authorization": f"Bearer {scoped_tool_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# allowed_agent_ids enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_allowed_agent_ids_blocks_other_agent(client, scoped_agent_key):
    """A key restricted to scoped-agent-caller cannot query another agent.

    Note: this hits the scope check before the ownership check because
    the target agent_id is not in allowed_agent_ids.
    """
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "agent-99"}},
        headers={"Authorization": f"Bearer {scoped_agent_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["type"].endswith("/scope-violation")


@pytest.mark.asyncio
async def test_allowed_agent_ids_permits_listed_agent(client, scoped_agent_key):
    """A key restricted to scoped-agent-caller can query that agent."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "scoped-agent-caller"}},
        headers={"Authorization": f"Bearer {scoped_agent_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# Admin scope allows all tools (including admin tools)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_scope_allows_write_tool(client, admin_key):
    """An admin-scoped key can call write tools."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "deposit", "params": {"agent_id": "admin-agent", "amount": 10.0}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_admin_scope_allows_read_tool(client, admin_key):
    """An admin-scoped key can call read tools."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "admin-agent"}},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# write scope allows read + write, blocks admin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_scope_allows_read_and_write(client, api_key):
    """Default key (read+write) can call both read and write tools."""
    # read tool
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200

    # write tool
    resp = await client.post(
        "/v1/execute",
        json={"tool": "deposit", "params": {"agent_id": "test-agent", "amount": 5.0}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Backward compatibility: unscoped key works as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backward_compat_unscoped_key(client, api_key):
    """A key created without explicit scopes (the api_key fixture) works normally."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
