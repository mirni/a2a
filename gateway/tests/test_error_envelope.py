"""Tests for RFC 9457 Problem Details error envelope (P0-5)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_error_response_has_request_id_header(client, api_key):
    """Error responses should include X-Request-ID in the response header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},  # Missing required agent_id
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert "x-request-id" in resp.headers, "Error response must contain X-Request-ID header"
    assert isinstance(resp.headers["x-request-id"], str)
    assert len(resp.headers["x-request-id"]) > 0


async def test_error_response_request_id_only_in_header(client, api_key):
    """request_id must be in X-Request-ID header, not in the body."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    # request_id must NOT be in the body
    assert "request_id" not in body
    # The X-Request-ID header must be set
    assert "x-request-id" in resp.headers


async def test_401_error_has_request_id_header(client):
    """401 (missing key) error should have X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "x"}},
    )
    assert resp.status_code == 401
    assert "x-request-id" in resp.headers


async def test_429_error_has_request_id_header(client, api_key, app):
    """429 error should have X-Request-ID header."""
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
    assert "x-request-id" in resp.headers


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


async def test_error_envelope_rfc9457_structure(client, api_key):
    """Error envelope should follow RFC 9457: {type, title, status, detail}."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "type" in body
    assert "title" in body
    assert "status" in body
    assert "detail" in body


async def test_error_content_type_is_problem_json(client, api_key):
    """Error responses should have Content-Type: application/problem+json."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"] == "application/problem+json"
