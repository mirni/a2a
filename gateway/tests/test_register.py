"""Tests for P2-7: Self-service registration endpoint."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_register_returns_key_and_wallet(client):
    """POST /v1/register creates a free-tier key + wallet with signup bonus."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "new-agent-register"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert "api_key" in data
    assert data["agent_id"] == "new-agent-register"
    assert data["tier"] == "free"
    assert data["balance"] >= 0


async def test_register_duplicate_agent_returns_409(client):
    """Registering the same agent_id twice returns 409."""
    resp1 = await client.post(
        "/v1/register",
        json={"agent_id": "dup-agent"},
    )
    assert resp1.status_code in (200, 201)

    resp2 = await client.post(
        "/v1/register",
        json={"agent_id": "dup-agent"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["type"].endswith("/already-exists")


async def test_register_missing_agent_id_returns_400(client):
    """Missing agent_id returns 400."""
    resp = await client.post(
        "/v1/register",
        json={},
    )
    assert resp.status_code == 400


async def test_register_key_works_for_tool_call(client):
    """The API key from registration can be used to call a tool."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "working-agent"},
    )
    assert resp.status_code in (200, 201)
    api_key = resp.json()["api_key"]

    # Use the key to call get_balance
    resp2 = await client.post(
        "/v1/execute",
        json={
            "tool": "get_balance",
            "params": {"agent_id": "working-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 200


async def test_register_no_auth_required(client):
    """Registration endpoint does not require auth."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "no-auth-agent"},
    )
    # Should NOT return 401
    assert resp.status_code != 401


async def test_register_key_creation_failure_returns_structured_error(client, app):
    """If key_manager.create_key() raises, return RFC 9457 error, not raw 500."""
    original_create_key = app.state.ctx.key_manager.create_key

    async def _broken_create_key(*args, **kwargs):
        raise RuntimeError("key storage is down")

    app.state.ctx.key_manager.create_key = _broken_create_key
    try:
        resp = await client.post(
            "/v1/register",
            json={"agent_id": "broken-key-agent"},
        )
        assert resp.status_code == 500
        data = resp.json()
        # RFC 9457 requires 'type' field
        assert "type" in data
        assert "detail" in data
    finally:
        app.state.ctx.key_manager.create_key = original_create_key


async def test_register_extra_fields_rejected(client):
    """Extra fields in request body should be rejected (extra=forbid)."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "extra-field-agent", "evil": "payload"},
    )
    assert resp.status_code == 400
