"""Tests for rate limit headers on /v1/execute responses (P0-1) and other endpoints (I-4)."""

from __future__ import annotations

import pytest

from gateway.src.deps.rate_limit import (
    RateLimitError,
    ServiceError,
    TierError,
    build_rate_limit_headers,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for build_rate_limit_headers
# ---------------------------------------------------------------------------


def test_build_rate_limit_headers_basic():
    headers = build_rate_limit_headers(100, 10)
    assert headers["X-RateLimit-Limit"] == "100"
    assert int(headers["X-RateLimit-Remaining"]) == 90
    assert 0 < int(headers["X-RateLimit-Reset"]) <= 3600


def test_build_rate_limit_headers_over_limit():
    headers = build_rate_limit_headers(100, 150)
    assert headers["X-RateLimit-Remaining"] == "0"


def test_build_rate_limit_headers_at_limit():
    headers = build_rate_limit_headers(100, 100)
    assert headers["X-RateLimit-Remaining"] == "0"


def test_build_rate_limit_headers_zero_rate_count():
    headers = build_rate_limit_headers(500, 0)
    assert headers["X-RateLimit-Remaining"] == "500"


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


def test_tier_error_attributes():
    err = TierError("free", "register_webhook", "pro")
    assert err.tier == "free"
    assert err.tool_name == "register_webhook"
    assert err.required_tier == "pro"
    assert "free" in str(err)


def test_rate_limit_error_global():
    err = RateLimitError(500, 500)
    assert "500/500" in str(err)


def test_rate_limit_error_per_tool():
    err = RateLimitError(10, 10, tool_name="search_services")
    assert "search_services" in str(err)


def test_service_error():
    err = ServiceError("Rate limit service unavailable")
    assert "unavailable" in str(err)


# ---------------------------------------------------------------------------
# Admin tier bypass (integration)
# ---------------------------------------------------------------------------


async def test_admin_tier_no_rate_limit_headers(client, admin_api_key):
    """Admin-tier responses should NOT include rate-limit headers."""
    resp = await client.get(
        "/v1/billing/wallets/admin-agent/balance",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    # Admin tier should not have rate limit headers
    assert "x-ratelimit-limit" not in resp.headers


async def test_successful_response_has_rate_limit_headers(client, api_key):
    """Every successful /v1/execute response must include X-RateLimit-* headers."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers


async def test_rate_limit_header_values_are_correct(client, api_key):
    """X-RateLimit-Limit should match tier config, Remaining should be non-negative."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200

    limit = int(resp.headers["x-ratelimit-limit"])
    remaining = int(resp.headers["x-ratelimit-remaining"])
    reset = int(resp.headers["x-ratelimit-reset"])

    assert limit > 0, "Limit must be positive"
    assert remaining >= 0, "Remaining must be non-negative"
    assert remaining <= limit, "Remaining must not exceed limit"
    assert 0 < reset <= 3600, "Reset must be between 1 and 3600 seconds"


async def test_rate_limit_remaining_decreases(client, api_key):
    """After multiple calls, Remaining should decrease."""
    resp1 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    remaining1 = int(resp1.headers["x-ratelimit-remaining"])

    resp2 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    remaining2 = int(resp2.headers["x-ratelimit-remaining"])

    assert remaining2 < remaining1, "Remaining should decrease after each call"


async def test_429_response_has_rate_limit_headers(client, api_key, app):
    """A 429 response should also include X-RateLimit-* headers."""
    # Artificially exhaust the rate limit by setting the count very high
    ctx = app.state.ctx
    key_info = await ctx.key_manager.validate_key(api_key)
    agent_id = key_info["agent_id"]

    from paywall_src.tiers import get_tier_config

    tier_config = get_tier_config("free")
    limit = tier_config.rate_limit_per_hour

    # Record enough rate events to exceed the limit (including burst)
    for _ in range(limit + 100):
        await ctx.paywall_storage.record_rate_event(agent_id, "gateway", "get_balance")

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 429
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers
    assert int(resp.headers["x-ratelimit-remaining"]) == 0


# ---------------------------------------------------------------------------
# I-4: Rate limit headers on other endpoints
# ---------------------------------------------------------------------------


async def test_pricing_has_rate_limit_headers(client):
    """GET /v1/pricing should include X-RateLimit-* headers."""
    resp = await client.get("/v1/pricing")
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers


async def test_health_has_rate_limit_headers(client):
    """GET /v1/health should include X-RateLimit-* headers."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers


async def test_batch_has_rate_limit_headers(client, api_key):
    """POST /v1/batch should include X-RateLimit-* headers."""
    resp = await client.post(
        "/v1/batch",
        json={
            "calls": [
                {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
            ]
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-ratelimit-limit" in resp.headers
    assert "x-ratelimit-remaining" in resp.headers
    assert "x-ratelimit-reset" in resp.headers
