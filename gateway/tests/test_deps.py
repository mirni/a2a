"""Tests for gateway.src.deps — shared FastAPI dependencies."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_require_tool_returns_tool_context(client, api_key):
    """Valid API key + known tool -> ToolContext with correct fields."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "balance" in body


async def test_require_tool_rejects_missing_key(client):
    """No API key -> 401."""
    resp = await client.get("/v1/billing/wallets/test-agent/balance")
    assert resp.status_code == 401


async def test_require_tool_rejects_invalid_key(client):
    """Bad API key -> 401."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": "Bearer invalid-key-xxx"},
    )
    assert resp.status_code == 401


async def test_finalize_response_adds_charged_header(client, api_key):
    """X-Charged header must be present on successful responses."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "X-Charged" in resp.headers


async def test_finalize_response_adds_request_id(client, api_key):
    """X-Request-ID header must be present."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers


async def test_finalize_response_serializes_money(client, api_key):
    """Monetary values must be serialized as strings."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # balance should be a string (serialized money)
    assert isinstance(body["balance"], str)


async def test_finalize_response_adds_rate_limit_headers(client, api_key):
    """Rate limit headers for non-admin, non-x402 requests."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers
