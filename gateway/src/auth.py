"""API key extraction from HTTP requests."""

from __future__ import annotations

from starlette.requests import Request


def extract_api_key(request: Request) -> str | None:
    """Extract an API key from the request.

    Checks in order:
    1. Authorization: Bearer <key>
    2. X-API-Key header
    3. ?api_key= query parameter
    """
    # 1. Authorization header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    # 2. X-API-Key header
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header:
        return api_key_header.strip()

    # 3. Query parameter
    api_key_param = request.query_params.get("api_key", "")
    if api_key_param:
        return api_key_param.strip()

    return None
