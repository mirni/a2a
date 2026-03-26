"""Tests for rate limiter."""

import asyncio
import time

import pytest

from src.rate_limiter import RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_requests_within_limit(self):
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)
        for _ in range(10):
            await limiter.acquire()
        # Should not raise or block significantly

    @pytest.mark.asyncio
    async def test_throttles_when_exhausted(self):
        limiter = RateLimiter(max_requests=2, window_seconds=1.0)
        await limiter.acquire()
        await limiter.acquire()
        # Third acquire should take measurable time
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3  # Should wait for token replenishment

    @pytest.mark.asyncio
    async def test_refills_over_time(self):
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)
        # Exhaust all tokens
        for _ in range(10):
            await limiter.acquire()
        # Wait for partial refill
        await asyncio.sleep(0.5)
        # Should be able to acquire some tokens now
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should not wait long since tokens refilled during sleep
        assert elapsed < 0.3

    @pytest.mark.asyncio
    async def test_wait_for_rate_limit(self):
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)
        start = time.monotonic()
        await limiter.wait_for_rate_limit(retry_after=0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1
