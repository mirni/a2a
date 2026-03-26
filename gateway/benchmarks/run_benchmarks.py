#!/usr/bin/env python3
"""Run all benchmark scenarios and produce a combined JSON report.

Each scenario gets a fresh app with isolated temporary databases.

Usage:
    cd gateway
    PYTHONPATH=/tmp/pylib:$(pwd)/.. python3 benchmarks/run_benchmarks.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Bootstrap product imports
import gateway.src.bootstrap  # noqa: F401

from gateway.src.app import create_app
from gateway.src.lifespan import lifespan
from gateway.benchmarks.bench_runner import BenchmarkReport, BenchmarkResult, build_system_info
from gateway.benchmarks.scenarios import ALL_SCENARIOS


async def run_scenario_with_fresh_app(
    scenario_name: str,
    scenario_func,
) -> list[BenchmarkResult]:
    """Run a single scenario with a fresh app and isolated temp databases."""
    with tempfile.TemporaryDirectory(prefix=f"bench_{scenario_name}_") as tmpdir:
        os.environ["A2A_DATA_DIR"] = tmpdir
        os.environ["BILLING_DSN"] = f"sqlite:///{tmpdir}/billing.db"
        os.environ["PAYWALL_DSN"] = f"sqlite:///{tmpdir}/paywall.db"
        os.environ["PAYMENTS_DSN"] = f"sqlite:///{tmpdir}/payments.db"
        os.environ["MARKETPLACE_DSN"] = f"sqlite:///{tmpdir}/marketplace.db"
        os.environ["TRUST_DSN"] = f"sqlite:///{tmpdir}/trust.db"

        app = create_app()
        ctx_manager = lifespan(app)
        await ctx_manager.__aenter__()
        try:
            results = await scenario_func(app)
            return results
        finally:
            await ctx_manager.__aexit__(None, None, None)


async def main() -> None:
    """Run all benchmarks and write the report."""
    report = BenchmarkReport(
        system_info=build_system_info(),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )

    print("=" * 70)
    print("A2A Gateway Benchmark Suite")
    print("=" * 70)
    print()

    for scenario_name, scenario_func in ALL_SCENARIOS:
        print(f"Running: {scenario_name} ...")
        try:
            results = await run_scenario_with_fresh_app(scenario_name, scenario_func)
            report.results.extend(results)
            for r in results:
                print(
                    f"  {r.scenario_name}: "
                    f"{r.rps} rps, "
                    f"p50={r.p50_ms}ms, p95={r.p95_ms}ms, p99={r.p99_ms}ms, "
                    f"errors={r.error_count}/{r.total_requests}"
                )
                if r.extra:
                    for k, v in r.extra.items():
                        print(f"    {k}: {v}")
        except Exception as exc:
            print(f"  FAILED: {exc}")
        print()

    # Write JSON report
    report_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)

    print("=" * 70)
    print("Summary")
    print("=" * 70)
    summary = report.to_dict()["summary"]
    print(f"  Total scenarios:  {summary['total_scenarios']}")
    print(f"  Scenarios passed: {summary['scenarios_passed']}")
    print(f"  Total errors:     {summary['total_errors']}")
    print(f"  Report written:   {report_path}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
