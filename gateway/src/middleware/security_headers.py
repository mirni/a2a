"""Security headers middleware.

Injects a fixed set of hardened security headers into every HTTP
response. The list is intentionally static and cheap so the middleware
never allocates per-request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["SecurityHeadersMiddleware"]

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"),
    (b"content-security-policy", b"default-src 'none'"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
]


class SecurityHeadersMiddleware:
    """ASGI middleware that injects hardened security headers into every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http",):
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers_list: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers_list.extend(_SECURITY_HEADERS)
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
