"""Tests for metrics pipeline fix and async-safe locking.

Covers:
- P0: Metrics actually increment after HTTP requests (via middleware)
- P0: /v1/metrics endpoint reflects real request counts
- P0: Error metrics increment on 4xx responses
- P0: Latency histogram data is present after requests
- P2: Metrics class uses asyncio-compatible synchronization, not threading.Lock
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from gateway.src.middleware import Metrics

# ---------------------------------------------------------------------------
# P0: Integration tests — metrics pipeline wired end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoint_counts_after_requests(client, api_key):
    """After N requests, /v1/metrics must show a2a_requests_total >= N."""
    Metrics.reset()

    n = 3
    for _ in range(n):
        await client.get("/v1/health")

    resp = await client.get("/v1/metrics")
    assert resp.status_code == 200
    text = resp.text

    # Parse the requests_total value from the Prometheus text output
    for line in text.splitlines():
        if line.startswith("a2a_requests_total "):
            value = int(line.split()[-1])
            assert value >= n, f"Expected a2a_requests_total >= {n} after {n} health requests, got {value}"
            break
    else:
        pytest.fail("a2a_requests_total line not found in /v1/metrics output")


@pytest.mark.asyncio
async def test_metrics_errors_increment_on_bad_request(client):
    """After a 400 error, /v1/metrics must show a2a_errors_total >= 1."""
    Metrics.reset()

    # Send a malformed execute request to trigger a 400
    resp = await client.post("/v1/execute", content=b"not-json")
    assert resp.status_code == 400

    resp = await client.get("/v1/metrics")
    text = resp.text

    for line in text.splitlines():
        if line.startswith("a2a_errors_total "):
            value = int(line.split()[-1])
            assert value >= 1, f"Expected a2a_errors_total >= 1 after a 400 error, got {value}"
            break
    else:
        pytest.fail("a2a_errors_total line not found in /v1/metrics output")


@pytest.mark.asyncio
async def test_metrics_latency_recorded_after_requests(client):
    """After requests, /v1/metrics must include latency histogram data."""
    Metrics.reset()

    await client.get("/v1/health")

    resp = await client.get("/v1/metrics")
    text = resp.text

    for line in text.splitlines():
        if line.startswith("a2a_request_duration_ms_count "):
            value = int(line.split()[-1])
            assert value >= 1, f"Expected a2a_request_duration_ms_count >= 1 after request, got {value}"
            break
    else:
        pytest.fail("a2a_request_duration_ms_count not found in /v1/metrics output")


# ---------------------------------------------------------------------------
# P2: Metrics class must use asyncio-compatible synchronization
# ---------------------------------------------------------------------------


def test_metrics_does_not_use_threading_lock():
    """Metrics._lock must NOT be a threading.Lock (blocks event loop)."""
    lock = Metrics._lock
    # threading.Lock is a factory function (not a class) in newer Python,
    # so isinstance() doesn't work. Check the module instead:
    # asyncio.Lock → module "asyncio.locks", threading.Lock → module "_thread"
    lock_module = type(lock).__module__
    assert lock_module != "_thread", f"Metrics._lock is from {lock_module}, expected asyncio.locks (asyncio.Lock)"


def test_metrics_uses_asyncio_lock():
    """Metrics._lock must be an asyncio.Lock instance."""
    lock = Metrics._lock
    assert isinstance(lock, asyncio.Lock), f"Metrics._lock is {type(lock).__name__}, expected asyncio.Lock"


def test_metrics_record_request_is_async():
    """Metrics.record_request must be an async (coroutine) function."""
    assert inspect.iscoroutinefunction(Metrics.record_request), (
        "Metrics.record_request should be async to use asyncio.Lock"
    )


def test_metrics_record_error_is_async():
    """Metrics.record_error must be an async (coroutine) function."""
    assert inspect.iscoroutinefunction(Metrics.record_error), "Metrics.record_error should be async to use asyncio.Lock"


def test_metrics_record_latency_is_async():
    """Metrics.record_latency must be an async (coroutine) function."""
    assert inspect.iscoroutinefunction(Metrics.record_latency), (
        "Metrics.record_latency should be async to use asyncio.Lock"
    )
