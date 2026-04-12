"""HTTPS enforcement middleware (audit H2).

Cloudflare terminates TLS and forwards ``X-Forwarded-Proto`` to mark
the original scheme. When ``FORCE_HTTPS=1`` is set we refuse plaintext
HTTP calls for mutating methods and 308-redirect safe methods.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

__all__ = ["HttpsEnforcementMiddleware"]

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _force_https_enabled() -> bool:
    """Read FORCE_HTTPS flag at request time so ops can toggle without restart."""
    value = os.environ.get("FORCE_HTTPS", "").strip().lower()
    return value in ("1", "true", "yes", "on")


class HttpsEnforcementMiddleware:
    """ASGI middleware that redirects/rejects plaintext HTTP requests.

    Cloudflare terminates TLS and forwards X-Forwarded-Proto to mark the
    original scheme. When FORCE_HTTPS=1:
      - X-Forwarded-Proto: http + safe method (GET/HEAD/OPTIONS) → 308 to https://
      - X-Forwarded-Proto: http + mutating method (POST/PUT/PATCH/DELETE) → 400
      - X-Forwarded-Proto: https → pass through
      - no X-Forwarded-Proto → assume trusted direct connection, pass through

    Defense-in-depth alongside Cloudflare "Always Use HTTPS" rule. Using 308
    (not 302) so clients preserve the request method on safe methods per RFC 7538.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not _force_https_enabled():
            await self.app(scope, receive, send)
            return

        # Extract X-Forwarded-Proto header
        headers = dict(scope.get("headers", []))
        xfp = headers.get(b"x-forwarded-proto", b"").decode("latin-1").strip().lower()

        # No header (direct connection) or https → pass through
        if not xfp or xfp == "https":
            await self.app(scope, receive, send)
            return

        # Plaintext HTTP detected — redirect or reject based on method
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")
        query_string = scope.get("query_string", b"").decode("latin-1")
        host = headers.get(b"host", b"api.greenhelix.net").decode("latin-1")

        if method in _SAFE_METHODS:
            # 308 Permanent Redirect (preserves method per RFC 7538)
            target = f"https://{host}{path}"
            if query_string:
                target = f"{target}?{query_string}"
            await send(
                {
                    "type": "http.response.start",
                    "status": 308,
                    "headers": [
                        (b"location", target.encode("latin-1")),
                        (b"content-length", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        # Mutating method over HTTP — refuse (don't silently redirect)
        body = json.dumps(
            {
                "type": "https://api.greenhelix.net/errors/https-required",
                "title": "HTTPS Required",
                "status": 400,
                "detail": (
                    "This endpoint requires HTTPS. Retry the request over "
                    "https:// — refusing to redirect mutating methods to "
                    "avoid silent protocol downgrade."
                ),
                "instance": path,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
