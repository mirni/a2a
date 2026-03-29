"""Smoke tests for the benchmark infrastructure.

These wrap each scenario as a pytest test with basic assertions:
- Throughput > 0
- No crashes
- Benchmark harness produces valid results

Run with:
    cd gateway
    PYTHONPATH=/tmp/pylib:$(pwd)/.. python3 -m pytest benchmarks/test_benchmarks.py -x -v
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


import gateway.src.bootstrap  # noqa: F401
from gateway.benchmarks.bench_runner import (
    BenchmarkResult,
    build_system_info,
    generate_run_id,
)
from gateway.benchmarks.scenarios import (
    scenario_execute_paid_tools,
    scenario_execute_pipeline,
    scenario_health_throughput,
    scenario_pricing_throughput,
    scenario_rate_limiter_burst,
    scenario_wallet_stress,
)
from gateway.src.app import create_app
from gateway.src.lifespan import lifespan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Provide a temporary data directory for all databases."""
    return str(tmp_path)


@pytest.fixture
async def app(tmp_data_dir, monkeypatch):
    """Create a Starlette app with lifespan managed."""
    monkeypatch.setenv("A2A_DATA_DIR", tmp_data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{tmp_data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{tmp_data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{tmp_data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{tmp_data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{tmp_data_dir}/trust.db")

    application = create_app()
    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    yield application
    await ctx_manager.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Unit tests for bench_runner utilities
# ---------------------------------------------------------------------------


def test_generate_run_id_uses_sha3():
    """Verify run ID generation uses SHA-3 (sha3_256)."""
    ts = 1700000000.0
    params = {"scenario": "test", "concurrency": 10}
    run_id = generate_run_id(ts, params)

    # Independently verify using hashlib sha3_256
    payload = f"{ts}:{json.dumps(params, sort_keys=True)}"
    expected = hashlib.sha3_256(payload.encode("utf-8")).hexdigest()[:16]
    assert run_id == expected
    assert len(run_id) == 16


def test_generate_run_id_deterministic():
    """Same inputs produce the same run ID."""
    ts = 1700000000.0
    params = {"a": 1, "b": 2}
    assert generate_run_id(ts, params) == generate_run_id(ts, params)


def test_generate_run_id_varies():
    """Different inputs produce different run IDs."""
    params = {"a": 1}
    id1 = generate_run_id(1.0, params)
    id2 = generate_run_id(2.0, params)
    assert id1 != id2


def test_build_system_info():
    """System info contains expected keys."""
    info = build_system_info()
    assert "python_version" in info
    assert "platform" in info


# ---------------------------------------------------------------------------
# Scenario smoke tests (small N to run fast)
# ---------------------------------------------------------------------------


def _assert_valid_results(results: list[BenchmarkResult]) -> None:
    """Shared assertions for benchmark results."""
    assert len(results) > 0
    for r in results:
        assert r.rps > 0, f"RPS should be > 0, got {r.rps}"
        assert r.total_requests > 0
        assert r.duration_sec > 0
        assert r.p50_ms >= 0
        assert r.p95_ms >= 0
        assert r.p99_ms >= 0
        assert 0.0 <= r.error_rate <= 1.0
        assert len(r.run_id) == 16


@pytest.mark.asyncio
async def test_scenario_health_throughput(app):
    """Smoke test: health endpoint throughput."""
    results = await scenario_health_throughput(app, total_requests=20, concurrency_levels=[1, 5])
    _assert_valid_results(results)
    for r in results:
        assert r.error_count == 0, f"Health checks should not error: {r.error_count}"


@pytest.mark.asyncio
async def test_scenario_pricing_throughput(app):
    """Smoke test: pricing endpoint throughput."""
    results = await scenario_pricing_throughput(app, total_requests=20, concurrency_levels=[1, 5])
    _assert_valid_results(results)
    for r in results:
        assert r.error_count == 0, f"Pricing should not error: {r.error_count}"


@pytest.mark.asyncio
async def test_scenario_execute_pipeline(app):
    """Smoke test: execute pipeline (get_balance)."""
    results = await scenario_execute_pipeline(app, total_requests=20, concurrency_levels=[1, 5])
    _assert_valid_results(results)
    for r in results:
        assert r.error_count == 0, f"Execute pipeline should not error: {r.error_count}"


@pytest.mark.asyncio
async def test_scenario_execute_paid_tools(app):
    """Smoke test: execute with paid tools (create_intent)."""
    results = await scenario_execute_paid_tools(app, total_requests=10)
    _assert_valid_results(results)


@pytest.mark.asyncio
async def test_scenario_wallet_stress(app):
    """Smoke test: concurrent wallet operations."""
    results = await scenario_wallet_stress(app, total_ops=20)
    _assert_valid_results(results)
    # Balance consistency check
    for r in results:
        if "balance_consistent" in r.extra:
            assert r.extra["balance_consistent"], (
                f"Balance inconsistent: final={r.extra.get('final_balance')}, "
                f"expected={r.extra.get('expected_balance')}"
            )


@pytest.mark.asyncio
async def test_scenario_rate_limiter_burst(app):
    """Smoke test: rate limiter under burst."""
    results = await scenario_rate_limiter_burst(app, total_requests=150)
    _assert_valid_results(results)
    for r in results:
        success = r.extra.get("success_count", 0)
        limited = r.extra.get("rate_limited_count", 0)
        assert success > 0, "Some requests should succeed"
        assert limited > 0, "Some requests should be rate-limited"
        assert success == 100, f"Exactly 100 should succeed (free tier limit), got {success}"
        assert limited == 50, f"Exactly 50 should be rate-limited, got {limited}"
