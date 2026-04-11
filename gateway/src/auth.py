"""API key extraction from HTTP requests.

Hardened in v1.2.4 (audit v1.2.3 NEW-CRIT-1/2) to strip surrounding
whitespace from the extracted key and to accept a more permissive but
deterministic form of the ``Authorization`` header (RFC 9110 §11.1
says scheme tokens are case-insensitive; linear whitespace between the
scheme and credential is allowed).
"""

from __future__ import annotations

import logging

from fastapi import Request

logger = logging.getLogger("a2a.auth")

# Characters we treat as whitespace around the extracted credential.
# Includes SP, HT, CR, LF so smuggled values do not survive.
_AUTH_STRIP_CHARS = " \t\r\n"


def extract_api_key(request: Request) -> str | None:
    """Extract an API key from the request.

    Checks in order:
    1. ``Authorization: Bearer <key>`` — scheme match is case-insensitive
       per RFC 9110 §11.1. Surrounding whitespace on the credential is
       stripped so ``Bearer <key> `` and ``Bearer <key>\\t`` both
       resolve to ``<key>``.
    2. ``X-API-Key`` header — also stripped of surrounding whitespace.

    Empty / whitespace-only values yield ``None`` (→ 401).
    """
    # 1. Authorization header
    auth = request.headers.get("authorization", "")
    if auth:
        # Split on the first run of whitespace so ``Bearer   <key>`` works.
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            candidate = parts[1].strip(_AUTH_STRIP_CHARS)
            if candidate:
                return candidate

    # 2. X-API-Key header
    api_key_header = request.headers.get("x-api-key", "")
    if api_key_header:
        candidate = api_key_header.strip(_AUTH_STRIP_CHARS)
        if candidate:
            return candidate

    return None
