"""Core benchmark infrastructure for the A2A gateway.

Provides an async benchmark runner that measures throughput, latency percentiles,
and error rates using httpx AsyncClient with ASGITransport (pure ASGI, no server).

Unique run IDs are generated using SHA-3 (sha3_256) hashing of timestamp + params.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import sys
import time
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

# Ensure project root is on sys.path
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def generate_run_id(timestamp: float, params: dict[str, Any]) -> str:
    """Generate a unique run ID using SHA-3 (sha3_256) hash of timestamp + params."""
    payload = f"{timestamp}:{json.dumps(params, sort_keys=True)}"
    return hashlib.sha3_256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""

    scenario_name: str
    concurrency: int
    total_requests: int
    duration_sec: float
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_count: int
    error_rate: float
    run_id: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    """Combined report for all benchmark scenarios."""

    results: list[BenchmarkResult] = field(default_factory=list)
    system_info: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_info": self.system_info,
            "timestamp": self.timestamp,
            "results": [r.to_dict() for r in self.results],
            "summary": {
                "total_scenarios": len(self.results),
                "total_errors": sum(r.error_count for r in self.results),
                "scenarios_passed": sum(1 for r in self.results if r.error_rate < 1.0),
            },
        }


def compute_percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from a sorted list of values."""
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * pct / 100.0)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


# Type for a request-maker callable: takes (client, iteration_index) -> status_code
RequestFunc = Callable[[httpx.AsyncClient, int], Coroutine[Any, Any, int]]


async def run_benchmark(
    app: Any,
    scenario_name: str,
    request_func: RequestFunc,
    total_requests: int = 100,
    concurrency: int = 10,
    setup_func: Callable[..., Coroutine[Any, Any, None]] | None = None,
) -> BenchmarkResult:
    """Run a benchmark scenario against the given ASGI app.

    Args:
        app: Starlette ASGI application.
        scenario_name: Human-readable scenario name.
        request_func: Async callable(client, index) -> http_status_code.
        total_requests: Number of requests to issue.
        concurrency: Number of concurrent tasks.
        setup_func: Optional async setup callable(client, app) invoked once.

    Returns:
        BenchmarkResult with latency percentiles and throughput.
    """
    run_params = {
        "scenario": scenario_name,
        "total_requests": total_requests,
        "concurrency": concurrency,
    }
    run_id = generate_run_id(time.time(), run_params)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
        if setup_func is not None:
            await setup_func(client, app)

        latencies: list[float] = []
        errors = 0
        semaphore = asyncio.Semaphore(concurrency)

        async def _issue(idx: int) -> None:
            nonlocal errors
            async with semaphore:
                t0 = time.perf_counter()
                try:
                    status = await request_func(client, idx)
                    elapsed = (time.perf_counter() - t0) * 1000  # ms
                    latencies.append(elapsed)
                    if status >= 500:
                        errors += 1
                except Exception:
                    elapsed = (time.perf_counter() - t0) * 1000
                    latencies.append(elapsed)
                    errors += 1

        wall_start = time.perf_counter()
        tasks = [asyncio.create_task(_issue(i)) for i in range(total_requests)]
        await asyncio.gather(*tasks)
        wall_end = time.perf_counter()

        duration = wall_end - wall_start
        sorted_lat = sorted(latencies)

        return BenchmarkResult(
            scenario_name=scenario_name,
            concurrency=concurrency,
            total_requests=total_requests,
            duration_sec=round(duration, 4),
            rps=round(total_requests / duration, 2) if duration > 0 else 0.0,
            p50_ms=round(compute_percentile(sorted_lat, 50), 3),
            p95_ms=round(compute_percentile(sorted_lat, 95), 3),
            p99_ms=round(compute_percentile(sorted_lat, 99), 3),
            error_count=errors,
            error_rate=round(errors / total_requests, 4) if total_requests > 0 else 0.0,
            run_id=run_id,
        )


async def run_benchmark_multi_concurrency(
    app: Any,
    scenario_name: str,
    request_func: RequestFunc,
    total_requests: int = 100,
    concurrency_levels: list[int] | None = None,
    setup_func: Callable[..., Coroutine[Any, Any, None]] | None = None,
) -> list[BenchmarkResult]:
    """Run a benchmark at multiple concurrency levels.

    Returns a list of BenchmarkResult, one per concurrency level.
    """
    if concurrency_levels is None:
        concurrency_levels = [1, 10, 50]

    results: list[BenchmarkResult] = []
    for i, conc in enumerate(concurrency_levels):
        # Only run setup once (on the first concurrency level)
        result = await run_benchmark(
            app=app,
            scenario_name=f"{scenario_name} (c={conc})",
            request_func=request_func,
            total_requests=total_requests,
            concurrency=conc,
            setup_func=setup_func if i == 0 else None,
        )
        results.append(result)
    return results


def build_system_info() -> dict[str, Any]:
    """Collect system metadata for the benchmark report."""
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
    }
