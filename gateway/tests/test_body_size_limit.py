"""Tests for P3-6: JSON 413 response for oversized request bodies.

The BodySizeLimitMiddleware must return a structured JSON 413 response
(not HTML) when the request body exceeds the configured limit (1 MB).
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# P3-6  Body size limit returns JSON 413
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_body_returns_json_413(client):
    """A request with Content-Length exceeding 1 MB must receive a JSON 413 response."""
    oversized_payload = b"x" * (1_048_576 + 1)  # 1 MB + 1 byte

    resp = await client.post(
        "/v1/execute",
        content=oversized_payload,
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code == 413
    assert resp.headers["content-type"] == "application/json"

    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["message"] == "Request body exceeds maximum size of 1MB"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_oversized_content_length_header_returns_json_413(client):
    """A request declaring Content-Length > 1 MB (via header) must be rejected
    even if no body bytes are actually sent."""
    resp = await client.post(
        "/v1/execute",
        content=b"small",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "2000000",  # 2 MB declared
        },
    )

    assert resp.status_code == 413
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["message"] == "Request body exceeds maximum size of 1MB"
    assert "request_id" in body


@pytest.mark.asyncio
async def test_request_within_limit_passes_through(client, api_key):
    """A request body within the 1 MB limit should not be blocked by the middleware."""
    small_payload = json.dumps({"tool": "get_balance", "params": {"agent_id": "test-agent"}})

    resp = await client.post(
        "/v1/execute",
        content=small_payload.encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    # Should NOT be 413 -- the request passes through the middleware
    assert resp.status_code != 413


@pytest.mark.asyncio
async def test_exactly_at_limit_passes_through(client):
    """A request body exactly at the 1 MB limit should pass through (not rejected)."""
    exact_payload = b"x" * 1_048_576  # exactly 1 MB

    resp = await client.post(
        "/v1/execute",
        content=exact_payload,
        headers={"Content-Type": "application/json"},
    )

    # Should NOT be 413 -- exactly at the limit is allowed
    assert resp.status_code != 413


@pytest.mark.asyncio
async def test_get_request_not_affected(client):
    """GET requests (which typically have no body) should not be affected."""
    resp = await client.get("/v1/health")

    assert resp.status_code == 200
    assert resp.status_code != 413
