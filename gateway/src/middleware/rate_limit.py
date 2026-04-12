"""Public endpoint rate-limit middleware.

Applies IP-based rate limiting only to the small set of unauthenticated
public endpoints (``/v1/health``, ``/v1/pricing``, …). All other paths
pass through untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .client_ip import _extract_client_ip

__all__ = ["PublicRateLimitMiddleware"]

# Paths subject to public (unauthenticated) IP-based rate limiting.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/v1/health",
        "/v1/pricing",
        "/v1/openapi.json",
        "/v1/onboarding",
        "/v1/metrics",
    }
)


def _is_public_path(path: str) -> bool:
    """Return True if *path* matches a public endpoint (exact or prefix)."""
    if path in _PUBLIC_PATHS:
        return True
    # /v1/pricing/{tool} and /v1/pricing/summary
    if path.startswith("/v1/pricing/"):
        return True
    return False


class PublicRateLimitMiddleware:
    """ASGI middleware that enforces IP-based rate limiting on public endpoints.

    Requires ``app.state.public_rate_limiter`` to be set (a
    :class:`~gateway.src.rate_limit_headers.PublicRateLimiter` instance).
    If the limiter is not present, requests pass through without enforcement.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_public_path(path):
            await self.app(scope, receive, send)
            return

        # Retrieve limiter from app state (set during lifespan)
        app_state = scope.get("app")
        limiter = None
        if app_state is not None:
            limiter = getattr(getattr(app_state, "state", None), "public_rate_limiter", None)

        if limiter is None:
            await self.app(scope, receive, send)
            return

        # Prefer the IP already resolved by ClientIpResolutionMiddleware
        # (which honours A2A_TRUSTED_PROXIES). Fall back to re-resolving
        # if the upstream middleware is not installed.
        client_ip = (scope.get("state") or {}).get("client_ip") or _extract_client_ip(scope)
        allowed, remaining, retry_after = limiter.record(client_ip)

        if not allowed:
            # Return 429 Too Many Requests (RFC 9457)
            from gateway.src.errors import problem_json_bytes

            body = problem_json_bytes(
                429,
                "rate_limit_exceeded",
                "Too many requests. Please retry later.",
                instance=path,
            )

            headers = [
                (b"content-type", b"application/problem+json"),
                (b"retry-after", str(retry_after).encode("latin-1")),
                (b"x-ratelimit-limit", str(limiter.limit).encode("latin-1")),
                (b"x-ratelimit-remaining", b"0"),
                (b"x-ratelimit-reset", str(retry_after).encode("latin-1")),
            ]

            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": headers,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": body,
                }
            )
            return

        # Allowed — store limiter info on scope state for route handlers
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["public_rate_limiter"] = limiter
        scope["state"]["client_ip"] = client_ip

        await self.app(scope, receive, send)
