"""Observability middleware: correlation IDs, metrics, public rate limiting, security headers, and structured logging."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.responses import Response

# ---------------------------------------------------------------------------
# 1. Correlation ID Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 1b. Security Headers Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 2. Public Rate Limit Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------

# Paths subject to public (unauthenticated) IP-based rate limiting.
_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/v1/health",
        "/v1/pricing",
        "/v1/openapi.json",
        "/v1/onboarding",
        "/v1/metrics",
    }
)


def _extract_client_ip(scope: dict) -> str:
    """Extract client IP from the ASGI scope.

    Checks X-Forwarded-For first (for reverse-proxy setups), then falls
    back to the ASGI client tuple.
    """
    headers = dict(scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").strip()
    if forwarded:
        # X-Forwarded-For: client, proxy1, proxy2 — take the leftmost
        return forwarded.split(",")[0].strip()

    client = scope.get("client")
    if client:
        return client[0]

    return "unknown"


def _is_public_path(path: str) -> bool:
    """Return True if *path* matches a public endpoint (exact or prefix)."""
    if path in _PUBLIC_PATHS:
        return True
    # /v1/pricing/{tool} and /v1/pricing/summary
    if path.startswith("/v1/pricing/"):
        return True
    return False


class PublicRateLimitMiddleware:
    """ASGI middleware that enforces IP-based rate limiting on public endpoints.

    Requires ``app.state.public_rate_limiter`` to be set (a
    :class:`~gateway.src.rate_limit_headers.PublicRateLimiter` instance).
    If the limiter is not present, requests pass through without enforcement.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not _is_public_path(path):
            await self.app(scope, receive, send)
            return

        # Retrieve limiter from app state (set during lifespan)
        app_state = scope.get("app")
        limiter = None
        if app_state is not None:
            limiter = getattr(getattr(app_state, "state", None), "public_rate_limiter", None)

        if limiter is None:
            await self.app(scope, receive, send)
            return

        client_ip = _extract_client_ip(scope)
        allowed, remaining, retry_after = limiter.record(client_ip)

        if not allowed:
            # Return 429 Too Many Requests (RFC 9457)
            from gateway.src.errors import problem_json_bytes

            body = problem_json_bytes(
                429,
                "rate_limit_exceeded",
                "Too many requests. Please retry later.",
                instance=path,
            )

            headers = [
                (b"content-type", b"application/problem+json"),
                (b"retry-after", str(retry_after).encode("latin-1")),
                (b"x-ratelimit-limit", str(limiter.limit).encode("latin-1")),
                (b"x-ratelimit-remaining", b"0"),
                (b"x-ratelimit-reset", str(retry_after).encode("latin-1")),
            ]

            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": headers,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": body,
                }
            )
            return

        # Allowed — store limiter info on scope state for route handlers
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["public_rate_limiter"] = limiter
        scope["state"]["client_ip"] = client_ip

        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# 3. Metrics singleton
# ---------------------------------------------------------------------------


class Metrics:
    """Simple in-process metrics collector (async-safe).

    Uses asyncio.Lock for non-blocking synchronization within the
    single-threaded async event loop.
    """

    requests_total: int = 0
    requests_by_tool: dict[str, int] = {}
    errors_total: int = 0
    latency_samples: list[float] = []

    _lock = asyncio.Lock()
    _MAX_LATENCY_SAMPLES = 1000

    # -- mutators -----------------------------------------------------------

    @classmethod
    async def record_request(cls, tool: str | None = None) -> None:
        async with cls._lock:
            cls.requests_total += 1
            if tool is not None:
                cls.requests_by_tool[tool] = cls.requests_by_tool.get(tool, 0) + 1

    @classmethod
    async def record_error(cls) -> None:
        async with cls._lock:
            cls.errors_total += 1

    @classmethod
    async def record_latency(cls, ms: float) -> None:
        async with cls._lock:
            cls.latency_samples.append(ms)
            if len(cls.latency_samples) > cls._MAX_LATENCY_SAMPLES:
                cls.latency_samples = cls.latency_samples[-cls._MAX_LATENCY_SAMPLES :]

    @classmethod
    def reset(cls) -> None:
        """Reset all counters. Synchronous for use in test setup."""
        cls.requests_total = 0
        cls.requests_by_tool = {}
        cls.errors_total = 0
        cls.latency_samples = []

    # -- exposition ----------------------------------------------------------

    @classmethod
    async def to_prometheus(cls) -> str:
        async with cls._lock:
            count = len(cls.latency_samples)
            total_ms = sum(cls.latency_samples)
            requests = cls.requests_total
            errors = cls.errors_total
            by_tool = dict(cls.requests_by_tool)

        lines = [
            "# HELP a2a_requests_total Total requests processed",
            "# TYPE a2a_requests_total counter",
            f"a2a_requests_total {requests}",
            "# HELP a2a_errors_total Total errors",
            "# TYPE a2a_errors_total counter",
            f"a2a_errors_total {errors}",
            "# HELP a2a_request_duration_ms Request duration in milliseconds",
            "# TYPE a2a_request_duration_ms summary",
            f"a2a_request_duration_ms_count {count}",
            f"a2a_request_duration_ms_sum {total_ms}",
        ]
        # Per-tool request counters
        if by_tool:
            lines.append("# HELP a2a_requests_by_tool_total Requests per tool")
            lines.append("# TYPE a2a_requests_by_tool_total counter")
            for tool_name, tool_count in sorted(by_tool.items()):
                lines.append(f'a2a_requests_by_tool_total{{tool="{tool_name}"}} {tool_count}')
        return "\n".join(lines) + "\n"


async def metrics_handler(request: Request) -> Response:
    """Starlette route handler that serves Prometheus text exposition."""
    return Response(
        content=await Metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


# ---------------------------------------------------------------------------
# 3b. Metrics Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------


class MetricsMiddleware:
    """ASGI middleware that records request count, errors, and latency for every HTTP request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code: int | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await Metrics.record_request()
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            await Metrics.record_error()
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            await Metrics.record_latency(elapsed_ms)

        if status_code is not None and status_code >= 400:
            await Metrics.record_error()


# ---------------------------------------------------------------------------
# 4. Body Size Limit Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 5. Request Timeout Middleware (raw ASGI interface)
# ---------------------------------------------------------------------------

# Default per-request timeout: 30 seconds
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0


class RequestTimeoutMiddleware:
    """ASGI middleware that enforces a per-request timeout.

    If the downstream handler takes longer than ``timeout_seconds``,
    the request is cancelled and a 504 Gateway Timeout response is returned.
    """

    def __init__(self, app: Any, timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> None:
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
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


# ---------------------------------------------------------------------------
# 6. Structured JSON logging
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        return json.dumps(log_entry, default=str)


def setup_structured_logging() -> None:
    """Configure the root logger with JSON-formatted output."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# HTTPS Enforcement Middleware (audit H2)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Agent ID Length Validation Middleware
# ---------------------------------------------------------------------------

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
