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
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    result = data["result"]
    assert "api_key" in result
    assert result["agent_id"] == "new-agent-register"
    assert result["tier"] == "free"
    assert result["balance"] >= 0


async def test_register_duplicate_agent_returns_409(client):
    """Registering the same agent_id twice returns 409."""
    resp1 = await client.post(
        "/v1/register",
        json={"agent_id": "dup-agent"},
    )
    assert resp1.status_code == 200

    resp2 = await client.post(
        "/v1/register",
        json={"agent_id": "dup-agent"},
    )
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "already_exists"


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
    assert resp.status_code == 200
    api_key = resp.json()["result"]["api_key"]

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
    assert resp2.json()["success"] is True


async def test_register_no_auth_required(client):
    """Registration endpoint does not require auth."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "no-auth-agent"},
    )
    # Should NOT return 401
    assert resp.status_code != 401
