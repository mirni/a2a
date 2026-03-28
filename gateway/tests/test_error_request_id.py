"""Tests for P1-11: Correlation ID (request_id) in error response bodies."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_error_response_contains_request_id(client, api_key):
    """Error responses should include a request_id field."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    # P0-5 added request_id to error responses
    assert "request_id" in body


async def test_error_request_id_matches_header(client, api_key):
    """The request_id in error body should match the X-Request-ID header on the request."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool_xyz", "params": {}},
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Request-ID": "custom-correlation-123",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert body.get("request_id") == "custom-correlation-123"


async def test_unknown_tool_error_has_request_id(client, api_key):
    """Unknown tool error response has request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "bogus_tool_name", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "request_id" in body


async def test_missing_key_error_has_request_id(client):
    """Missing API key error should also include request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "x"}},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert "request_id" in body


async def test_tier_error_has_request_id(client, api_key):
    """Tier insufficient error should include request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "register_webhook", "params": {
            "agent_id": "test-agent",
            "url": "https://example.com",
            "event_types": ["test"],
        }},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # register_webhook requires pro tier
    assert resp.status_code == 403
    body = resp.json()
    assert "request_id" in body


async def test_product_exception_has_request_id(client, api_key):
    """Product exceptions (e.g., intent not found) should include request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404
    body = resp.json()
    assert "request_id" in body


async def test_success_response_has_request_id(client, api_key):
    """Successful responses should also include request_id."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "request_id" in body
