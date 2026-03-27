"""Tests for POST /execute."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_execute_missing_tool(client, api_key):
    resp = await client.post(
        "/v1/execute",
        json={"params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_execute_unknown_tool(client, api_key):
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_execute_missing_key(client):
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test"}},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "missing_key"


@pytest.mark.asyncio
async def test_execute_invalid_key(client):
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test"}},
        headers={"Authorization": "Bearer invalid_key_12345"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_execute_get_balance(client, api_key, app):
    resp = await client.post(
        "/v1/execute",
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
        "/v1/execute",
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
        "/v1/execute",
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
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_execute_api_key_query_param(client, api_key):
    """API key via query parameter should also work."""
    resp = await client.post(
        f"/v1/execute?api_key={api_key}",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_execute_insufficient_tier(client, api_key):
    """Free tier should not access pro-tier tools like create_escrow."""
    resp = await client.post(
        "/v1/execute",
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
        "/v1/execute",
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
    # 1.5% of amount=10 → max(0.01, min(10.0, 0.15)) = 0.15
    assert data["charged"] == 0.15


@pytest.mark.asyncio
async def test_execute_insufficient_balance(client, app):
    """Tool with per_call cost should fail if wallet has no balance."""
    await client.get("/health")  # ensure lifespan
    ctx = app.state.ctx

    # Create wallet with zero balance
    await ctx.tracker.wallet.create("broke-agent", initial_balance=0.0)
    key_info = await ctx.key_manager.create_key("broke-agent", tier="free")

    resp = await client.post(
        "/v1/execute",
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
        "/v1/execute",
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
        "/v1/execute",
        content=b"not json",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_execute_delete_server(client, pro_api_key, app):
    """Pro tier should be able to delete a server via gateway."""
    ctx = app.state.ctx

    # Register a server first
    await ctx.trust_api.register_server(
        name="To Delete", url="https://delete.com", server_id="del-001",
    )

    resp = await client.post(
        "/v1/execute",
        json={"tool": "delete_server", "params": {"server_id": "del-001"}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["deleted"] is True

    # Verify it's gone
    server = await ctx.trust_api.storage.get_server("del-001")
    assert server is None


@pytest.mark.asyncio
async def test_execute_delete_server_not_found(client, pro_api_key, app):
    """Deleting a non-existent server should return an error."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "delete_server", "params": {"server_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # Should get an error response (not 200)
    assert resp.status_code != 200


@pytest.mark.asyncio
async def test_execute_delete_server_requires_pro(client, api_key):
    """Free tier should not be able to delete a server."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "delete_server", "params": {"server_id": "any"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_tier"


@pytest.mark.asyncio
async def test_execute_update_server(client, pro_api_key, app):
    """Pro tier should be able to update a server via gateway."""
    ctx = app.state.ctx

    # Register a server first
    await ctx.trust_api.register_server(
        name="Old Name", url="https://old.com", server_id="upd-001",
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "update_server",
            "params": {"server_id": "upd-001", "name": "New Name", "url": "https://new.com"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["name"] == "New Name"
    assert data["result"]["url"] == "https://new.com"


@pytest.mark.asyncio
async def test_execute_update_server_not_found(client, pro_api_key):
    """Updating a non-existent server should return an error."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "update_server",
            "params": {"server_id": "nonexistent", "name": "X"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code != 200


@pytest.mark.asyncio
async def test_execute_global_audit_log(client, pro_api_key, app):
    """Pro tier should be able to query the global audit log."""
    ctx = app.state.ctx

    # Record some audit entries
    await ctx.paywall_storage.record_audit(
        agent_id="agent-x", function="test_fn", tier="pro",
    )
    await ctx.paywall_storage.record_audit(
        agent_id="agent-y", function="other_fn", tier="free",
    )

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_global_audit_log", "params": {"limit": 50}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    entries = data["result"]["entries"]
    # Should have at least the 2 entries we just created (plus any from gateway usage)
    assert len(entries) >= 2
    agents = {e["agent_id"] for e in entries}
    assert "agent-x" in agents
    assert "agent-y" in agents


@pytest.mark.asyncio
async def test_execute_global_audit_log_requires_pro(client, api_key):
    """Free tier should not access the global audit log."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_global_audit_log", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_tier"


@pytest.mark.asyncio
async def test_execute_create_and_capture_intent(client, api_key, app):
    """End-to-end: create an intent and then capture it."""
    ctx = app.state.ctx

    # Create payee wallet
    await ctx.tracker.wallet.create("payee-agent", initial_balance=0.0)

    # Create intent
    resp = await client.post(
        "/v1/execute",
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
        "/v1/execute",
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
