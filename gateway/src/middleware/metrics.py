"""In-process metrics collector + Prometheus exposition middleware.

Hosts:

* :class:`Metrics` – thread-/coroutine-safe counter aggregator.
* :func:`metrics_handler` – Starlette route that renders the
  Prometheus text exposition format, stitched together with the
  gatekeeper-specific metrics module.
* :class:`MetricsMiddleware` – ASGI middleware that records request
  count, error count, and per-request latency.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import Response

__all__ = ["Metrics", "MetricsMiddleware", "metrics_handler"]


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
    # v1.2.4: gatekeeper telemetry (per-tier counters + duration / solver
    # histograms) lives in its own module so route handlers can record
    # observations without importing the gateway-wide middleware, but is
    # stitched onto the same /v1/metrics document.
    from gateway.src.gatekeeper_metrics import GatekeeperMetrics

    body = await Metrics.to_prometheus()
    body += await GatekeeperMetrics.to_prometheus()
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4",
    )


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
