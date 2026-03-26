"""Tests for observability features: correlation IDs, metrics."""

from __future__ import annotations

import pytest

from gateway.src.middleware import Metrics


@pytest.mark.asyncio
async def test_correlation_id_generated(client):
    """Responses should include an X-Request-ID header."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers


@pytest.mark.asyncio
async def test_correlation_id_echoed(client):
    """If X-Request-ID is sent, it should be echoed back."""
    resp = await client.get(
        "/v1/health",
        headers={"X-Request-ID": "test-correlation-123"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id") == "test-correlation-123"


@pytest.mark.asyncio
async def test_metrics_endpoint(client, api_key):
    """GET /v1/metrics should return Prometheus text format."""
    # Make a request to generate some metrics
    Metrics.reset()
    await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    resp = await client.get("/v1/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "a2a_requests_total" in text
    assert "a2a_errors_total" in text
    assert "a2a_request_duration_ms" in text


@pytest.mark.asyncio
async def test_metrics_counter_increments(client, api_key):
    """Metrics counters should increment on tool execution."""
    Metrics.reset()

    await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert Metrics.requests_total >= 1
    assert Metrics.requests_by_tool.get("get_balance", 0) >= 1


@pytest.mark.asyncio
async def test_signing_key_endpoint(client):
    """GET /v1/signing-key should return signing key info."""
    resp = await client.get("/v1/signing-key")
    assert resp.status_code == 200
    data = resp.json()
    assert "public_key" in data
    assert "algorithm" in data
