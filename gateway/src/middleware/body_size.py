"""Body size limit middleware.

Short-circuits requests whose ``Content-Length`` header declares a body
larger than the configured limit so the application is protected even
if an upstream nginx is bypassed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

__all__ = ["BodySizeLimitMiddleware", "DEFAULT_MAX_BODY_BYTES"]

_logger = logging.getLogger("a2a.middleware")

# Default maximum request body size: 1 MB
DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 * 1024 * 1024


class BodySizeLimitMiddleware:
    """ASGI middleware that rejects request bodies exceeding a configurable size limit.

    Inspects the Content-Length header (fast path). If Content-Length declares a
    body larger than ``max_bytes``, a 413 response is returned immediately.
    This protects the application even if nginx is bypassed.
    """

    def __init__(self, app: Any, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract correlation ID from scope state (set by CorrelationIDMiddleware)
        request_id = (scope.get("state") or {}).get("correlation_id", "")

        # Fast path: check Content-Length header if present
        headers = dict(scope.get("headers", []))
        content_length_raw = headers.get(b"content-length", b"").decode("latin-1")
        if content_length_raw:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                content_length = 0
            if content_length > self.max_bytes:
                await self._send_413(send, request_id=request_id)
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_413(send: Callable, request_id: str = "") -> None:
        """Send a 413 Payload Too Large response (RFC 9457)."""
        from gateway.src.errors import problem_json_bytes

        body = problem_json_bytes(
            413,
            "payload_too_large",
            "Request body exceeds maximum size of 1MB",
        )
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if request_id:
            headers.append((b"x-request-id", request_id.encode("latin-1")))
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": headers,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
