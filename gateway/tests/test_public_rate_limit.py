"""Tests for IP-based public endpoint rate limiting.

Validates that the PublicRateLimiter class correctly tracks requests per IP,
enforces limits, returns 429 when exceeded, and cleans up expired entries.
"""

from __future__ import annotations

import asyncio

import pytest

from gateway.src.rate_limit_headers import PublicRateLimiter, public_rate_limit_headers

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for PublicRateLimiter class
# ---------------------------------------------------------------------------


class TestPublicRateLimiterTracking:
    """PublicRateLimiter tracks requests per IP."""

    async def test_record_increments_count(self):
        limiter = PublicRateLimiter(limit=100, window_seconds=3600)
        allowed, remaining, retry_after = limiter.record("10.0.0.1")
        assert allowed is True
        assert remaining == 99

    async def test_remaining_decrements_after_each_request(self):
        limiter = PublicRateLimiter(limit=100, window_seconds=3600)

        _, remaining1, _ = limiter.record("10.0.0.1")
        _, remaining2, _ = limiter.record("10.0.0.1")
        _, remaining3, _ = limiter.record("10.0.0.1")

        assert remaining1 == 99
        assert remaining2 == 98
        assert remaining3 == 97


class TestPublicRateLimiterEnforcement:
    """PublicRateLimiter returns 429 after limit exceeded."""

    async def test_returns_blocked_after_limit_exceeded(self):
        limiter = PublicRateLimiter(limit=3, window_seconds=3600)

        limiter.record("10.0.0.1")
        limiter.record("10.0.0.1")
        limiter.record("10.0.0.1")

        allowed, remaining, retry_after = limiter.record("10.0.0.1")
        assert allowed is False
        assert remaining == 0

    async def test_retry_after_present_when_blocked(self):
        limiter = PublicRateLimiter(limit=1, window_seconds=3600)
        limiter.record("10.0.0.1")

        allowed, remaining, retry_after = limiter.record("10.0.0.1")
        assert allowed is False
        assert retry_after > 0
        assert retry_after <= 3600

    async def test_retry_after_is_zero_when_allowed(self):
        limiter = PublicRateLimiter(limit=10, window_seconds=3600)
        allowed, remaining, retry_after = limiter.record("10.0.0.1")
        assert allowed is True
        assert retry_after == 0


class TestPublicRateLimiterIsolation:
    """Different IPs have independent limits."""

    async def test_different_ips_independent(self):
        limiter = PublicRateLimiter(limit=2, window_seconds=3600)

        limiter.record("10.0.0.1")
        limiter.record("10.0.0.1")

        # IP 1 is now at limit
        allowed_ip1, _, _ = limiter.record("10.0.0.1")
        assert allowed_ip1 is False

        # IP 2 should still be allowed
        allowed_ip2, remaining_ip2, _ = limiter.record("10.0.0.2")
        assert allowed_ip2 is True
        assert remaining_ip2 == 1


class TestPublicRateLimiterExpiry:
    """Window expires and count resets (uses fake clock, no real sleeps)."""

    async def test_window_expiry_resets_count(self, monkeypatch):
        import gateway.src.rate_limit_headers as rl_mod

        fake_now = 1_000_000.0
        monkeypatch.setattr(rl_mod.time, "time", lambda: fake_now)

        limiter = PublicRateLimiter(limit=2, window_seconds=1)

        limiter.record("10.0.0.1")
        limiter.record("10.0.0.1")

        # At limit now
        allowed, _, _ = limiter.record("10.0.0.1")
        assert allowed is False

        # Advance clock past window
        fake_now += 1.1
        monkeypatch.setattr(rl_mod.time, "time", lambda: fake_now)

        # Should be allowed again
        allowed, remaining, _ = limiter.record("10.0.0.1")
        assert allowed is True
        assert remaining == 1

    async def test_cleanup_removes_expired_entries(self, monkeypatch):
        import gateway.src.rate_limit_headers as rl_mod

        fake_now = 1_000_000.0
        monkeypatch.setattr(rl_mod.time, "time", lambda: fake_now)

        limiter = PublicRateLimiter(limit=100, window_seconds=1)

        limiter.record("10.0.0.1")
        limiter.record("10.0.0.2")

        # Advance clock past window
        fake_now += 1.1
        monkeypatch.setattr(rl_mod.time, "time", lambda: fake_now)

        limiter.cleanup()

        # Internal state should have been cleaned
        assert len(limiter._requests) == 0


class TestPublicRateLimitHeadersIntegration:
    """public_rate_limit_headers() returns accurate remaining counts."""

    async def test_returns_actual_remaining(self):
        limiter = PublicRateLimiter(limit=100, window_seconds=3600)
        limiter.record("10.0.0.1")
        limiter.record("10.0.0.1")

        headers = public_rate_limit_headers(limiter=limiter, client_ip="10.0.0.1")
        assert headers["X-RateLimit-Limit"] == "100"
        assert headers["X-RateLimit-Remaining"] == "98"

    async def test_fallback_without_limiter(self):
        """When no limiter is provided, fall back to the old static behavior."""
        headers = public_rate_limit_headers()
        assert headers["X-RateLimit-Limit"] == "1000"
        assert headers["X-RateLimit-Remaining"] == "1000"


# ---------------------------------------------------------------------------
# Integration tests: 429 via HTTP on public endpoints
# ---------------------------------------------------------------------------


async def test_health_returns_429_when_rate_limited(app, client):
    """GET /v1/health returns 429 with Retry-After after limit exceeded."""
    # Install a tiny-limit limiter on app.state
    limiter = PublicRateLimiter(limit=2, window_seconds=3600)
    app.state.public_rate_limiter = limiter

    resp1 = await client.get("/v1/health")
    assert resp1.status_code == 200

    resp2 = await client.get("/v1/health")
    assert resp2.status_code == 200

    resp3 = await client.get("/v1/health")
    assert resp3.status_code == 429
    assert "retry-after" in resp3.headers
    assert int(resp3.headers["retry-after"]) > 0


async def test_pricing_returns_429_when_rate_limited(app, client):
    """GET /v1/pricing returns 429 with Retry-After after limit exceeded."""
    limiter = PublicRateLimiter(limit=2, window_seconds=3600)
    app.state.public_rate_limiter = limiter

    await client.get("/v1/pricing")
    await client.get("/v1/pricing")

    resp = await client.get("/v1/pricing")
    assert resp.status_code == 429
    assert "retry-after" in resp.headers


async def test_public_rate_limit_remaining_decrements_via_http(app, client):
    """X-RateLimit-Remaining should decrement with each request."""
    limiter = PublicRateLimiter(limit=100, window_seconds=3600)
    app.state.public_rate_limiter = limiter

    resp1 = await client.get("/v1/health")
    resp2 = await client.get("/v1/health")

    remaining1 = int(resp1.headers["x-ratelimit-remaining"])
    remaining2 = int(resp2.headers["x-ratelimit-remaining"])

    assert remaining1 == 99
    assert remaining2 == 98
