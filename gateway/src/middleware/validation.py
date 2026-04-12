"""Path validation middleware: agent-id length + encoded-separator reject.

Two narrow checks bundled together because they both run early in the
chain and share a target: legitimate ``/v1/`` traffic should never hit
oversized path segments or URL-encoded path separators, so we short
circuit them with a 400 before any route handler allocates.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

__all__ = [
    "AgentIdLengthMiddleware",
    "EncodedPathRejectionMiddleware",
]

_MAX_AGENT_ID_LENGTH = 128


class AgentIdLengthMiddleware:
    """ASGI middleware that rejects requests with oversized path segments.

    Any path segment longer than 128 characters in a /v1/ route gets a 422.
    This prevents abuse via oversized agent_id values in path params.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            if path.startswith("/v1/"):
                segments = path.split("/")
                for segment in segments:
                    if len(segment) > _MAX_AGENT_ID_LENGTH:
                        body = json.dumps(
                            {
                                "type": "https://api.greenhelix.net/errors/path-too-long",
                                "title": "Bad Request",
                                "status": 400,
                                "detail": f"Path segment exceeds maximum length of {_MAX_AGENT_ID_LENGTH} characters",
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
                        return
        await self.app(scope, receive, send)


# Encoded forms of "/" and "\" that must never appear inside a path.
# Upstream WAF / proxy rules typically match on literal ``/v1/infra/...``;
# letting ``%2F`` through would allow an attacker to spell the same path
# in a way those rules don't recognise. We read ``raw_path`` from the
# ASGI scope because ``scope["path"]`` is already %-decoded by uvicorn.
_ENCODED_PATH_SEPARATORS: tuple[bytes, ...] = (
    b"%2f",
    b"%2F",
    b"%5c",
    b"%5C",
)


class EncodedPathRejectionMiddleware:
    """Reject ``/v1/`` requests whose raw path contains an encoded ``/`` or ``\\``.

    Legitimate API paths never need to encode the separators. Rejecting
    them prevents upstream filter bypasses (audit v1.2.3 NEW-CRIT-3).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            raw_path: bytes = scope.get("raw_path") or path.encode()
            if (path.startswith("/v1") or raw_path.startswith(b"/v1")) and any(
                enc in raw_path for enc in _ENCODED_PATH_SEPARATORS
            ):
                body = json.dumps(
                    {
                        "type": "https://api.greenhelix.net/errors/encoded-path-separator",
                        "title": "Bad Request",
                        "status": 400,
                        "detail": (
                            "Encoded path separator (%2F, %2f, %5C, %5c) is "
                            "not allowed in /v1/ routes. Use literal '/' "
                            "in the request path."
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
                return
        await self.app(scope, receive, send)
