"""Observability middleware: correlation IDs, metrics, and structured logging."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import Response


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
                headers_list: list[tuple[bytes, bytes]] = list(
                    message.get("headers", [])
                )
                headers_list.append(
                    (b"x-request-id", correlation_id.encode("latin-1"))
                )
                message["headers"] = headers_list
            await send(message)

        await self.app(scope, receive, send_with_correlation_id)


# ---------------------------------------------------------------------------
# 2. Metrics singleton
# ---------------------------------------------------------------------------

class Metrics:
    """Simple in-process metrics collector (thread-safe)."""

    requests_total: int = 0
    requests_by_tool: dict[str, int] = {}
    errors_total: int = 0
    latency_samples: list[float] = []

    _lock = threading.Lock()
    _MAX_LATENCY_SAMPLES = 1000

    # -- mutators -----------------------------------------------------------

    @classmethod
    def record_request(cls, tool: str | None = None) -> None:
        with cls._lock:
            cls.requests_total += 1
            if tool is not None:
                cls.requests_by_tool[tool] = cls.requests_by_tool.get(tool, 0) + 1

    @classmethod
    def record_error(cls) -> None:
        with cls._lock:
            cls.errors_total += 1

    @classmethod
    def record_latency(cls, ms: float) -> None:
        with cls._lock:
            cls.latency_samples.append(ms)
            if len(cls.latency_samples) > cls._MAX_LATENCY_SAMPLES:
                cls.latency_samples = cls.latency_samples[-cls._MAX_LATENCY_SAMPLES :]

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls.requests_total = 0
            cls.requests_by_tool = {}
            cls.errors_total = 0
            cls.latency_samples = []

    # -- exposition ----------------------------------------------------------

    @classmethod
    def to_prometheus(cls) -> str:
        with cls._lock:
            count = len(cls.latency_samples)
            total_ms = sum(cls.latency_samples)

        lines = [
            "# HELP a2a_requests_total Total requests processed",
            "# TYPE a2a_requests_total counter",
            f"a2a_requests_total {cls.requests_total}",
            "# HELP a2a_errors_total Total errors",
            "# TYPE a2a_errors_total counter",
            f"a2a_errors_total {cls.errors_total}",
            "# HELP a2a_request_duration_ms Request duration in milliseconds",
            "# TYPE a2a_request_duration_ms summary",
            f"a2a_request_duration_ms_count {count}",
            f"a2a_request_duration_ms_sum {total_ms}",
        ]
        # Per-tool request counters
        if cls.requests_by_tool:
            lines.append("# HELP a2a_requests_by_tool_total Requests per tool")
            lines.append("# TYPE a2a_requests_by_tool_total counter")
            for tool_name, tool_count in sorted(cls.requests_by_tool.items()):
                lines.append(f'a2a_requests_by_tool_total{{tool="{tool_name}"}} {tool_count}')
        return "\n".join(lines) + "\n"


async def metrics_handler(request: Request) -> Response:
    """Starlette route handler that serves Prometheus text exposition."""
    return Response(
        content=Metrics.to_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


# ---------------------------------------------------------------------------
# 3. Structured JSON logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
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
