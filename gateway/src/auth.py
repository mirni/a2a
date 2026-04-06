"""API key extraction from HTTP requests."""

from __future__ import annotations

import logging

from fastapi import Request

logger = logging.getLogger("a2a.auth")


def extract_api_key(request: Request) -> str | None:
    """Extract an API key from the request.

    Checks in order:
    1. Authorization: Bearer <key>
    2. X-API-Key header
    """
    # 1. Authorization header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]

    # 2. X-API-Key header
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header:
        return api_key_header

    return None
