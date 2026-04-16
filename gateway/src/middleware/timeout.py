"""Per-request timeout middleware.

If the downstream handler takes longer than ``timeout_seconds``, the
request is cancelled and a 504 Gateway Timeout response is returned.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

__all__ = ["DEFAULT_REQUEST_TIMEOUT_SECONDS", "RequestTimeoutMiddleware"]

_logger = logging.getLogger("a2a.middleware")

# Default per-request timeout: 30 seconds
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0


_TIMEOUT_EXEMPT_PATHS = frozenset({"/v1/events/stream"})


class RequestTimeoutMiddleware:
    """ASGI middleware that enforces a per-request timeout.

    If the downstream handler takes longer than ``timeout_seconds``,
    the request is cancelled and a 504 Gateway Timeout response is returned.

    Long-lived streaming endpoints (SSE) are exempt from the timeout.
    """

    def __init__(self, app: Any, timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path", "") in _TIMEOUT_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            _logger.warning(
                "Request timed out after %.1fs: %s %s",
                self.timeout_seconds,
                scope.get("method", "?"),
                scope.get("path", "?"),
            )
            await self._send_504(send)

    @staticmethod
    async def _send_504(send: Callable) -> None:
        """Send a 504 Gateway Timeout response (RFC 9457)."""
        from gateway.src.errors import problem_json_bytes

        body = problem_json_bytes(504, "request_timeout", "Request timed out")
        await send(
            {
                "type": "http.response.start",
                "status": 504,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )
