"""Token bucket rate limiter for production API connectors."""

import asyncio
import time


class RateLimiter:
    """Async token bucket rate limiter.

    Enforces a maximum number of requests per time window. When the bucket
    is empty, callers wait until tokens replenish.
    """

    def __init__(self, max_requests: int = 100, window_seconds: float = 60.0):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window.
            window_seconds: Window duration in seconds.
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._tokens = float(max_requests)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self.max_requests / self.window_seconds)
        self._tokens = min(self.max_requests, self._tokens + new_tokens)
        self._last_refill = now

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Calculate wait time for next token
                wait_time = (1.0 - self._tokens) * (self.window_seconds / self.max_requests)
            await asyncio.sleep(wait_time)

    async def wait_for_rate_limit(self, retry_after: float | None = None) -> None:
        """Wait when an upstream rate limit (429) is hit.

        Args:
            retry_after: Seconds to wait from Retry-After header.
        """
        wait = retry_after if retry_after else self.window_seconds
        async with self._lock:
            self._tokens = 0.0
        await asyncio.sleep(wait)
