"""Tests for POST /execute."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_execute_missing_tool(client, api_key):
    resp = await client.post(
        "/execute",
        json={"params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_execute_unknown_tool(client, api_key):
    resp = await client.post(
        "/execute",
        json={"tool": "nonexistent", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_execute_missing_key(client):
    resp = await client.post(
        "/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test"}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "missing_key"


@pytest.mark.asyncio
async def test_execute_invalid_key(client):
    resp = await client.post(
        "/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test"}},
        headers={"Authorization": "Bearer invalid_key_12345"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_execute_get_balance(client, api_key, app):
    resp = await client.post(
        "/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "result" in data
    assert data["result"]["balance"] == 1000.0
    assert data["charged"] == 0.0


@pytest.mark.asyncio
async def test_execute_get_usage_summary(client, api_key):
    resp = await client.post(
        "/execute",
        json={"tool": "get_usage_summary", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "total_cost" in data["result"]
    assert "total_calls" in data["result"]


@pytest.mark.asyncio
async def test_execute_deposit(client, api_key):
    resp = await client.post(
        "/execute",
        json={"tool": "deposit", "params": {"agent_id": "test-agent", "amount": 50.0}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["new_balance"] == 1050.0


@pytest.mark.asyncio
async def test_execute_x_api_key_header(client, api_key):
    """API key via X-API-Key header should also work."""
    resp = await client.post(
        "/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_execute_api_key_query_param(client, api_key):
    """API key via query parameter should also work."""
    resp = await client.post(
        f"/execute?api_key={api_key}",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_execute_insufficient_tier(client, api_key):
    """Free tier should not access pro-tier tools like create_escrow."""
    resp = await client.post(
        "/execute",
        json={
            "tool": "create_escrow",
            "params": {"payer": "a", "payee": "b", "amount": 10},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_tier"


@pytest.mark.asyncio
async def test_execute_pro_tier_access(client, pro_api_key, app):
    """Pro tier should be able to access pro-tier tools."""
    # First create wallets for payer and payee
    ctx = app.state.ctx

    resp = await client.post(
        "/execute",
        json={
            "tool": "create_escrow",
            "params": {
                "payer": "pro-agent",
                "payee": "payee-agent",
                "amount": 10,
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["status"] == "held"
    assert data["charged"] == 1.0


@pytest.mark.asyncio
async def test_execute_insufficient_balance(client, app):
    """Tool with per_call cost should fail if wallet has no balance."""
    await client.get("/health")  # ensure lifespan
    ctx = app.state.ctx

    # Create wallet with zero balance
    await ctx.tracker.wallet.create("broke-agent", initial_balance=0.0)
    key_info = await ctx.key_manager.create_key("broke-agent", tier="free")

    resp = await client.post(
        "/execute",
        json={
            "tool": "create_intent",
            "params": {"payer": "broke-agent", "payee": "someone", "amount": 5},
        },
        headers={"Authorization": f"Bearer {key_info['key']}"},
    )
    assert resp.status_code == 402
    assert resp.json()["error"]["code"] == "insufficient_balance"


@pytest.mark.asyncio
async def test_execute_search_services(client, api_key):
    """Search services should work with empty marketplace."""
    resp = await client.post(
        "/execute",
        json={"tool": "search_services", "params": {"query": "test"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "services" in data["result"]


@pytest.mark.asyncio
async def test_execute_invalid_json(client, api_key):
    resp = await client.post(
        "/execute",
        content=b"not json",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_execute_create_and_capture_intent(client, api_key, app):
    """End-to-end: create an intent and then capture it."""
    ctx = app.state.ctx

    # Create payee wallet
    await ctx.tracker.wallet.create("payee-agent", initial_balance=0.0)

    # Create intent
    resp = await client.post(
        "/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "payee-agent",
                "amount": 25.0,
                "description": "test payment",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    intent_data = resp.json()["result"]
    assert intent_data["status"] == "pending"
    intent_id = intent_data["id"]

    # Capture intent
    resp = await client.post(
        "/execute",
        json={
            "tool": "capture_intent",
            "params": {"intent_id": intent_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    capture_data = resp.json()["result"]
    assert capture_data["status"] == "settled"
    assert capture_data["amount"] == 25.0
