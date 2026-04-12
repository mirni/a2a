"""Correlation ID middleware.

Propagates or generates an ``X-Request-ID`` header on every HTTP/WS
request so downstream logs and structured events can be tied back to a
single client interaction. The generated correlation id is also
exposed to FastAPI route handlers via ``request.state.correlation_id``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

__all__ = ["CorrelationIDMiddleware"]


class CorrelationIDMiddleware:
    """ASGI middleware that propagates or generates an X-Request-ID header."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # --- Extract or generate correlation id ---
        headers = dict(scope.get("headers", []))
        request_id_header = headers.get(b"x-request-id", b"").decode("latin-1")
        correlation_id = request_id_header if request_id_header else str(uuid.uuid4())

        # Store on scope["state"] so request.state.correlation_id works
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["correlation_id"] = correlation_id

        # --- Wrap send to inject the header into the response ---
        async def send_with_correlation_id(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers_list: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers_list.append((b"x-request-id", correlation_id.encode("latin-1")))
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_with_correlation_id)
