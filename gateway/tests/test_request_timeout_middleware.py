"""Tests for RequestTimeoutMiddleware SSE exemption.

The RequestTimeoutMiddleware enforces a 30-second timeout on HTTP
requests.  SSE streams (/v1/events/stream) are designed for long-lived
connections (up to 3600s) and must be exempt from this timeout.

v1.4.7 audit: SSE IncompleteRead regression caused by the 30s timeout
killing the streaming response mid-flight.
"""

from __future__ import annotations

import asyncio

import pytest

from gateway.src.middleware.timeout import RequestTimeoutMiddleware

pytestmark = pytest.mark.asyncio


async def test_sse_path_exempt_from_timeout():
    """SSE endpoint must not be killed by the request timeout middleware.

    A 30s timeout on a streaming endpoint causes IncompleteRead.  The
    middleware should skip timeout enforcement for /v1/events/stream.
    """

    completed = False

    async def slow_sse_app(scope, receive, send):
        nonlocal completed
        # Simulate an SSE response that takes longer than the timeout
        await asyncio.sleep(0.3)
        completed = True
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/event-stream")],
            }
        )
        await send({"type": "http.response.body", "body": b"data: ok\n\n"})

    middleware = RequestTimeoutMiddleware(slow_sse_app, timeout_seconds=0.1)

    scope = {"type": "http", "method": "GET", "path": "/v1/events/stream"}

    async def noop_receive():
        await asyncio.Event().wait()

    sent: list[dict] = []

    async def mock_send(msg):
        sent.append(msg)

    await middleware(scope, noop_receive, mock_send)

    # The slow app should have completed (not been timed out)
    assert completed is True
    assert any(m.get("status") == 200 for m in sent)


async def test_non_sse_path_still_times_out():
    """Normal endpoints must still be subject to the timeout."""

    async def slow_app(scope, receive, send):
        await asyncio.sleep(0.5)
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = RequestTimeoutMiddleware(slow_app, timeout_seconds=0.1)
    scope = {"type": "http", "method": "GET", "path": "/v1/payments/intents"}

    sent: list[dict] = []

    async def noop_receive():
        await asyncio.Event().wait()

    async def mock_send(msg):
        sent.append(msg)

    await middleware(scope, noop_receive, mock_send)

    # Should have received a 504 timeout response
    assert any(m.get("status") == 504 for m in sent)
