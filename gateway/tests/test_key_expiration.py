"""Tests for API key TTL/expiration enforcement (P2-6).

Verifies that:
- Keys with expires_at in the past are rejected with 401 at the gateway level.
- Keys with expires_at in the future are accepted normally.
- Keys with no expires_at (None) are accepted normally.
- ExpiredKeyError is raised at the KeyManager level.
- The expires_at field is correctly stored and returned.
"""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def expired_key(app, client):
    """Create an API key that expired 60 seconds ago."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("expired-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "expired-agent",
        tier="free",
        expires_at=time.time() - 60,
    )
    return key_info["key"]


@pytest.fixture
async def future_key(app, client):
    """Create an API key that expires 1 hour from now."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("future-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "future-agent",
        tier="free",
        expires_at=time.time() + 3600,
    )
    return key_info["key"]


@pytest.fixture
async def no_expiry_key(app, client):
    """Create an API key with no expiration (expires_at=None)."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("no-expiry-agent", initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(
        "no-expiry-agent",
        tier="free",
        expires_at=None,
    )
    return key_info["key"]


# ---------------------------------------------------------------------------
# Gateway-level expiration enforcement (HTTP layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_key_returns_401(client, expired_key):
    """An expired API key must be rejected with HTTP 401."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "expired-agent"}},
        headers={"Authorization": f"Bearer {expired_key}"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"].endswith("/expired-key")
    assert "expired" in body["detail"].lower()


@pytest.mark.asyncio
async def test_expired_key_error_message_is_informative(client, expired_key):
    """The error message for an expired key should mention expiration."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "expired-agent"}},
        headers={"Authorization": f"Bearer {expired_key}"},
    )
    assert resp.status_code == 401
    message = resp.json()["detail"]
    assert "expired" in message.lower()


@pytest.mark.asyncio
async def test_future_expiry_key_succeeds(client, future_key):
    """A key with expiration in the future should work normally."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "future-agent"}},
        headers={"Authorization": f"Bearer {future_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_no_expiry_key_succeeds(client, no_expiry_key):
    """A key with no expiration (None) should work normally."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "no-expiry-agent"}},
        headers={"Authorization": f"Bearer {no_expiry_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ---------------------------------------------------------------------------
# KeyManager-level expiration enforcement (unit-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_manager_raises_expired_key_error(app):
    """KeyManager.validate_key raises ExpiredKeyError for expired keys."""
    from paywall_src.keys import ExpiredKeyError

    ctx = app.state.ctx
    key_info = await ctx.key_manager.create_key(
        "unit-expired-agent",
        tier="free",
        expires_at=time.time() - 1,
    )
    with pytest.raises(ExpiredKeyError, match="expired"):
        await ctx.key_manager.validate_key(key_info["key"])


@pytest.mark.asyncio
async def test_key_manager_accepts_future_key(app):
    """KeyManager.validate_key accepts a key whose expires_at is in the future."""
    ctx = app.state.ctx
    key_info = await ctx.key_manager.create_key(
        "unit-future-agent",
        tier="free",
        expires_at=time.time() + 3600,
    )
    record = await ctx.key_manager.validate_key(key_info["key"])
    assert record["agent_id"] == "unit-future-agent"
    assert record["expires_at"] is not None
    assert record["expires_at"] > time.time()


@pytest.mark.asyncio
async def test_key_manager_accepts_no_expiry_key(app):
    """KeyManager.validate_key accepts a key with no expiration."""
    ctx = app.state.ctx
    key_info = await ctx.key_manager.create_key(
        "unit-no-expiry-agent",
        tier="free",
        expires_at=None,
    )
    record = await ctx.key_manager.validate_key(key_info["key"])
    assert record["agent_id"] == "unit-no-expiry-agent"
    assert record["expires_at"] is None


# ---------------------------------------------------------------------------
# Storage-level: expires_at is persisted correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expires_at_stored_on_creation(app):
    """The expires_at value is correctly stored and returned at creation."""
    ctx = app.state.ctx
    future_ts = time.time() + 7200
    key_info = await ctx.key_manager.create_key(
        "storage-agent",
        tier="free",
        expires_at=future_ts,
    )
    assert key_info["expires_at"] == future_ts


@pytest.mark.asyncio
async def test_expires_at_none_by_default(app):
    """When no expires_at is provided, it defaults to None."""
    ctx = app.state.ctx
    key_info = await ctx.key_manager.create_key(
        "default-expiry-agent",
        tier="free",
    )
    assert key_info["expires_at"] is None


@pytest.mark.asyncio
async def test_expires_at_persisted_in_lookup(app):
    """The expires_at value is returned correctly on lookup_key."""
    ctx = app.state.ctx
    future_ts = time.time() + 7200
    key_info = await ctx.key_manager.create_key(
        "lookup-agent",
        tier="free",
        expires_at=future_ts,
    )
    from paywall_src.keys import _hash_key

    record = await ctx.key_manager.storage.lookup_key(_hash_key(key_info["key"]))
    assert record is not None
    assert record["expires_at"] == future_ts
