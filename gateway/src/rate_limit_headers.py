"""Shared rate limit header helpers.

Provides header builders for both authenticated (per-tier) and
unauthenticated (public/default) endpoints, including IP-based
rate limiting for public endpoints via PublicRateLimiter.
"""

from __future__ import annotations

import math
import threading
import time

# Default public rate limit for unauthenticated endpoints (per hour)
_PUBLIC_RATE_LIMIT = 1000


class PublicRateLimiter:
    """IP-based sliding-window rate limiter for public endpoints.

    Tracks request timestamps per client IP in an in-memory dict.
    Thread-safe via a threading lock (also safe for single-threaded asyncio
    since all operations are non-blocking).

    Parameters:
        limit: Maximum number of requests allowed per window.
        window_seconds: Length of the sliding window in seconds.
    """

    def __init__(self, limit: int = 1000, window_seconds: int = 3600) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def record(self, client_ip: str) -> tuple[bool, int, int]:
        """Record a request from *client_ip* and check the rate limit.

        Returns:
            A tuple of (allowed, remaining, retry_after):
            - allowed: True if the request is within the limit.
            - remaining: Number of requests remaining in the current window.
            - retry_after: Seconds until the earliest request expires (0 if allowed).
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests.get(client_ip, [])

            # Prune expired timestamps for this IP
            timestamps = [ts for ts in timestamps if ts > cutoff]

            if len(timestamps) >= self.limit:
                # Blocked — compute retry_after from oldest request in window
                earliest = min(timestamps)
                retry_after = max(1, math.ceil((earliest + self.window_seconds) - now))
                self._requests[client_ip] = timestamps
                return False, 0, retry_after

            # Allowed — record this request
            timestamps.append(now)
            self._requests[client_ip] = timestamps
            remaining = max(0, self.limit - len(timestamps))
            return True, remaining, 0

    def remaining(self, client_ip: str) -> int:
        """Return the number of remaining requests for *client_ip* without recording."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            timestamps = self._requests.get(client_ip, [])
            active = sum(1 for ts in timestamps if ts > cutoff)
            return max(0, self.limit - active)

    def cleanup(self) -> None:
        """Remove all expired entries to prevent unbounded memory growth."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            expired_ips = []
            for ip, timestamps in self._requests.items():
                active = [ts for ts in timestamps if ts > cutoff]
                if active:
                    self._requests[ip] = active
                else:
                    expired_ips.append(ip)
            for ip in expired_ips:
                del self._requests[ip]


def public_rate_limit_headers(
    *,
    limiter: PublicRateLimiter | None = None,
    client_ip: str | None = None,
) -> dict[str, str]:
    """Build X-RateLimit-* headers for unauthenticated (public) endpoints.

    When *limiter* and *client_ip* are provided, returns accurate remaining
    counts based on actual tracked usage.  Otherwise falls back to the
    static default (backward-compatible).
    """
    if limiter is not None and client_ip is not None:
        remaining = limiter.remaining(client_ip)
        limit = limiter.limit
        window_seconds = float(limiter.window_seconds)
    else:
        remaining = _PUBLIC_RATE_LIMIT
        limit = _PUBLIC_RATE_LIMIT
        window_seconds = 3600.0

    reset = max(1, math.ceil(window_seconds - (time.time() % window_seconds)))
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
    }
