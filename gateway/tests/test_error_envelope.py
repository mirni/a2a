"""Tests for error envelope consistency with request_id (P0-5)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_error_response_includes_request_id(client, api_key):
    """Error responses should include request_id in the JSON body."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},  # Missing required agent_id
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "request_id" in body, "Error body must contain 'request_id'"
    assert isinstance(body["request_id"], str)
    assert len(body["request_id"]) > 0


async def test_error_response_request_id_matches_header(client, api_key):
    """request_id in body should match X-Request-ID in headers."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "request_id" in body
    # The X-Request-ID header is set by middleware
    header_id = resp.headers.get("x-request-id")
    assert header_id is not None
    assert body["request_id"] == header_id


async def test_401_error_includes_request_id(client):
    """401 (missing key) error should also include request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "x"}},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "request_id" in body


async def test_429_error_includes_request_id(client, api_key, app):
    """429 error should include request_id."""
    ctx = app.state.ctx
    key_info = await ctx.key_manager.validate_key(api_key)
    agent_id = key_info["agent_id"]

    from paywall_src.tiers import get_tier_config

    tier_config = get_tier_config("free")
    limit = tier_config.rate_limit_per_hour

    for _ in range(limit + 100):
        await ctx.paywall_storage.record_rate_event(agent_id, "gateway", "get_balance")

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 429
    body = resp.json()
    assert "request_id" in body


async def test_success_response_includes_request_id(client, api_key):
    """Successful responses should also include request_id for consistency."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "request_id" in body


async def test_error_envelope_structure(client, api_key):
    """Error envelope should have exact shape: {success, error: {code, message}, request_id}."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body.keys()) == {"success", "error", "request_id"}
    assert set(body["error"].keys()) == {"code", "message"}
