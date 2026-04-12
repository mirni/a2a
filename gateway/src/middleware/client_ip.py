"""Client IP resolution middleware and helpers (audit v1.2.3 CRIT-4).

Single source of truth for "which IP is this request actually coming
from". Forwarded headers are only trusted when the ASGI peer address
appears in ``A2A_TRUSTED_PROXIES``; otherwise the socket remote is
returned unchanged so spoofed headers cannot poison rate limiting or
logs.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

__all__ = [
    "ClientIpResolutionMiddleware",
    "_extract_client_ip",
    "_peer_ip",
    "_trusted_proxies",
]


def _trusted_proxies() -> frozenset[str]:
    """Return the set of ASGI peer IPs that are authorised to set XFF.

    Read from ``A2A_TRUSTED_PROXIES`` (comma-separated) at request time
    so ops can toggle without a restart. Default: empty set — meaning
    XFF is never trusted. This is the secure default per audit v1.2.3
    CRIT-4: without explicit opt-in, the gateway MUST ignore forwarded
    headers entirely and rely solely on the ASGI client tuple.
    """
    raw = os.environ.get("A2A_TRUSTED_PROXIES", "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def _peer_ip(scope: dict) -> str:
    """Return the ASGI peer IP (the socket-level remote address)."""
    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"


def _extract_client_ip(scope: dict) -> str:
    """Extract the resolved client IP from the ASGI scope.

    Audit v1.2.3 CRIT-4 hardening:
    * If the ASGI peer (socket remote address) is in ``A2A_TRUSTED_PROXIES``
      we may trust the leftmost entry of ``X-Forwarded-For`` (and fall back
      to ``X-Real-IP``) as the real client.
    * Otherwise forwarded headers are IGNORED entirely — the peer IP is
      returned so spoofed headers cannot poison rate limiting or logs.

    This function is the single source of truth for client IP resolution
    across the gateway. Call it from any middleware that needs the IP.
    """
    peer = _peer_ip(scope)
    trusted = _trusted_proxies()
    if peer not in trusted:
        # Untrusted (or direct) peer — forwarded headers are lies.
        return peer

    headers = dict(scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").strip()
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2 — take the leftmost
        return forwarded.split(",")[0].strip() or peer

    real_ip = headers.get(b"x-real-ip", b"").decode("latin-1").strip()
    if real_ip:
        return real_ip

    return peer


class ClientIpResolutionMiddleware:
    """ASGI middleware that resolves the client IP once per request.

    The resolved IP is stored on ``scope["state"]["client_ip"]`` so
    downstream middleware (rate limiting, logging) and route handlers
    can read it without re-running the trusted-proxy logic.

    Also emits ``X-Client-IP-Resolved`` as a response header so callers
    — and the audit v1.2.3 CRIT-4 regression tests — can observe which
    IP the gateway actually attributed the request to. This header is
    intentionally advisory and safe to expose: it's always either the
    socket peer or a proxy-attested value the operator opted into.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = _extract_client_ip(scope)
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["client_ip"] = client_ip

        header_value = client_ip.encode("latin-1")

        async def send_with_client_ip(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers_list: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers_list.append((b"x-client-ip-resolved", header_value))
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_with_client_ip)
