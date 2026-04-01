"""Tests for P1-11: Correlation ID (X-Request-ID) in error response headers."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_error_response_contains_request_id_header(client, api_key):
    """Error responses should include X-Request-ID in the response header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    # P0-5 added X-Request-ID to error response headers
    assert "x-request-id" in resp.headers


async def test_error_request_id_matches_header(client, api_key):
    """The X-Request-ID response header should echo the one from the request."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool_xyz", "params": {}},
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Request-ID": "custom-correlation-123",
        },
    )
    assert resp.status_code == 400
    assert resp.headers.get("x-request-id") == "custom-correlation-123"


async def test_unknown_tool_error_has_request_id_header(client, api_key):
    """Unknown tool error response has X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "bogus_tool_name", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert "x-request-id" in resp.headers


async def test_missing_key_error_has_request_id_header(client):
    """Missing API key error should also include X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "x"}},
    )
    assert resp.status_code == 401
    assert "x-request-id" in resp.headers


async def test_tier_error_has_request_id_header(client, api_key):
    """Tier insufficient error should include X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "test-agent",
                "url": "https://example.com",
                "event_types": ["test"],
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # register_webhook requires pro tier
    assert resp.status_code == 403
    assert "x-request-id" in resp.headers


async def test_product_exception_has_request_id_header(client, api_key):
    """Product exceptions (e.g., intent not found) should include X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404
    assert "x-request-id" in resp.headers


async def test_success_response_has_request_id(client, api_key):
    """Successful responses should also include X-Request-ID header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
