"""Tests for execute route fixes: auth ordering, rate limit headers, body size limit, timeout.

P0: Auth must run BEFORE param validation — unauthenticated users must not see param names.
P1: Rate limit headers in successful responses.
P1: Body size limit middleware (>1MB -> 413).
P2: Request timeout middleware.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# P0: Auth before validation — unauthenticated requests must NOT leak param names
# ---------------------------------------------------------------------------


async def test_unauth_known_tool_missing_params_returns_401_not_400(client):
    """An unauthenticated request to a known tool with missing required params
    must return 401 (missing key), NOT 400 with the param names leaked."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        # No auth header
    )
    # Must be 401 (auth error), NOT 400 (which would leak "agent_id" param name)
    assert resp.status_code == 401, (
        f"Expected 401 but got {resp.status_code}: unauthenticated request "
        f"should fail at auth, not at param validation. Body: {resp.json()}"
    )
    assert resp.json()["error"]["code"] == "missing_key"


async def test_invalid_key_known_tool_missing_params_returns_401_not_400(client):
    """An invalid-key request to a known tool with missing params must return 401,
    not 400 with param names."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": "Bearer totally_bogus_key_12345"},
    )
    assert resp.status_code == 401, (
        f"Expected 401 but got {resp.status_code}: invalid key request "
        f"should fail at auth, not param validation. Body: {resp.json()}"
    )


async def test_authenticated_missing_params_returns_400_with_param_names(client, api_key):
    """An authenticated request with missing required params SHOULD return 400
    with the param names (this is fine for authed users)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "missing_parameter"
    assert "agent_id" in body["error"]["message"]


# ---------------------------------------------------------------------------
# P1: Rate limit headers on successful execute responses
# ---------------------------------------------------------------------------


async def test_successful_execute_has_rate_limit_headers(client, api_key):
    """Successful /v1/execute must include X-RateLimit-Limit, Remaining, Reset."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers, "Missing X-RateLimit-Limit header"
    assert "x-ratelimit-remaining" in resp.headers, "Missing X-RateLimit-Remaining header"
    assert "x-ratelimit-reset" in resp.headers, "Missing X-RateLimit-Reset header"

    # Values must be sensible
    limit = int(resp.headers["x-ratelimit-limit"])
    remaining = int(resp.headers["x-ratelimit-remaining"])
    reset = int(resp.headers["x-ratelimit-reset"])
    assert limit > 0
    assert 0 <= remaining <= limit
    assert 0 < reset <= 3600


# ---------------------------------------------------------------------------
# P1: Body size limit middleware (>1MB -> 413)
# ---------------------------------------------------------------------------


async def test_oversized_body_returns_413(client, api_key):
    """A request body exceeding 1MB must be rejected with 413."""
    # Create a body larger than 1MB
    oversized_payload = "x" * (1024 * 1024 + 1)
    resp = await client.post(
        "/v1/execute",
        content=oversized_payload.encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 413, f"Expected 413 for oversized body but got {resp.status_code}"


async def test_normal_body_passes_size_check(client, api_key):
    """A normal-sized request body (<1MB) should not be rejected by size limit."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Should NOT be 413
    assert resp.status_code != 413, "Normal-sized body should not be rejected"
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# P2: Request timeout middleware
# ---------------------------------------------------------------------------


async def test_request_timeout_middleware_configured(app):
    """The app must have a RequestTimeoutMiddleware registered."""
    from gateway.src.middleware import RequestTimeoutMiddleware

    # Starlette stores registered middleware classes in app.user_middleware
    middleware_classes = [m.cls for m in app.user_middleware]
    assert RequestTimeoutMiddleware in middleware_classes, (
        f"RequestTimeoutMiddleware not found in middleware stack. Registered: {middleware_classes}"
    )
