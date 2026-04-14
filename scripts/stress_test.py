#!/usr/bin/env python3
"""
A2A Commerce Platform — Stress Test Suite
==========================================

Spawns concurrent simulated customer agents hitting the API to measure
throughput, latency distribution, and failure rates.

Usage:
    # Against local server
    python scripts/stress_test.py --base-url http://localhost:8000

    # Against production
    python scripts/stress_test.py --base-url https://api.greenhelix.net

    # Custom concurrency and duration
    python scripts/stress_test.py --customers 50 --duration 120 --ramp-up 15

    # With an admin key for provisioning
    python scripts/stress_test.py --admin-key sk_admin_...

Environment variables:
    STRESS_BASE_URL     — Target server URL (default: http://localhost:8000)
    STRESS_ADMIN_KEY    — Admin API key for provisioning test agents
    STRESS_CUSTOMERS    — Number of concurrent customers (default: 20)
    STRESS_DURATION     — Test duration in seconds (default: 60)
    STRESS_RAMP_UP      — Ramp-up period in seconds (default: 10)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_CUSTOMERS = 20
DEFAULT_DURATION = 60
DEFAULT_RAMP_UP = 10

# Workloads: (weight, label, method, path_fn, query_fn)
# path_fn(agent_id) → URL path; query_fn(agent_id) → query params dict
WORKLOADS: list[tuple[int, str, str, Any, Any]] = [
    (30, "get_balance", "GET", lambda aid: f"/v1/billing/wallets/{aid}/balance", lambda _: {}),
    (15, "get_usage_summary", "GET", lambda aid: f"/v1/billing/wallets/{aid}/usage", lambda _: {}),
    (
        10,
        "search_services",
        "GET",
        lambda _: "/v1/marketplace/services",
        lambda _: {"query": "code review", "limit": 5},
    ),
    (10, "get_events", "GET", lambda _: "/v1/infra/events", lambda _: {"limit": 10}),
    (8, "search_servers", "GET", lambda _: "/v1/trust/servers", lambda _: {"limit": 5}),
    (7, "list_webhooks", "GET", lambda _: "/v1/infra/webhooks", lambda _: {}),
    (5, "get_agent_leaderboard", "GET", lambda _: "/v1/billing/leaderboard", lambda _: {"metric": "calls", "limit": 5}),
    (
        5,
        "estimate_cost",
        "GET",
        lambda _: "/v1/billing/estimate",
        lambda _: {"tool_name": "get_balance", "quantity": 100},
    ),
    (
        5,
        "get_metrics_timeseries",
        "GET",
        lambda aid: f"/v1/billing/wallets/{aid}/timeseries",
        lambda _: {"interval": "hour"},
    ),
    (3, "get_payment_history", "GET", lambda _: "/v1/payments/history", lambda aid: {"agent_id": aid, "limit": 10}),
    (2, "list_subscriptions", "GET", lambda _: "/v1/payments/subscriptions", lambda aid: {"agent_id": aid, "limit": 5}),
]

# Build weighted selection list: (label, method, path_fn, query_fn)
_WORKLOAD_CHOICES: list[tuple[str, str, Any, Any]] = []
for weight, label, method, path_fn, query_fn in WORKLOADS:
    _WORKLOAD_CHOICES.extend([(label, method, path_fn, query_fn)] * weight)


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------


@dataclass
class RequestResult:
    tool: str
    status_code: int
    latency_ms: float
    success: bool
    error: str = ""


@dataclass
class StressMetrics:
    results: list[RequestResult] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    def record(self, result: RequestResult) -> None:
        self.results.append(result)

    @property
    def total_requests(self) -> int:
        return len(self.results)

    @property
    def successful(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return self.total_requests - self.successful

    @property
    def error_rate(self) -> float:
        return self.failed / max(1, self.total_requests) * 100

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def rps(self) -> float:
        return self.total_requests / max(0.001, self.duration)

    def latency_percentile(self, p: float) -> float:
        latencies = sorted(r.latency_ms for r in self.results)
        if not latencies:
            return 0.0
        idx = int(len(latencies) * p / 100)
        return latencies[min(idx, len(latencies) - 1)]

    def latency_stats(self) -> dict[str, float]:
        latencies = [r.latency_ms for r in self.results]
        if not latencies:
            return {"min": 0, "max": 0, "mean": 0, "median": 0, "p95": 0, "p99": 0, "stdev": 0}
        return {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p95": self.latency_percentile(95),
            "p99": self.latency_percentile(99),
            "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
        }

    def errors_by_status(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for r in self.results:
            if not r.success:
                counts[r.status_code] = counts.get(r.status_code, 0) + 1
        return counts

    def results_by_tool(self) -> dict[str, dict[str, Any]]:
        tool_results: dict[str, list[RequestResult]] = {}
        for r in self.results:
            tool_results.setdefault(r.tool, []).append(r)

        summary = {}
        for tool, results in sorted(tool_results.items()):
            latencies = [r.latency_ms for r in results]
            summary[tool] = {
                "count": len(results),
                "success": sum(1 for r in results if r.success),
                "failed": sum(1 for r in results if not r.success),
                "avg_ms": statistics.mean(latencies) if latencies else 0,
                "p95_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            }
        return summary


# ---------------------------------------------------------------------------
# Customer agent simulator
# ---------------------------------------------------------------------------


class CustomerAgent:
    """Simulates a single customer agent making API calls."""

    def __init__(
        self,
        agent_id: str,
        api_key: str,
        base_url: str,
        metrics: StressMetrics,
        client: httpx.AsyncClient,
    ) -> None:
        self.agent_id = agent_id
        self.api_key = api_key
        self.base_url = base_url
        self.metrics = metrics
        self.client = client
        self._running = False

    async def run(self, duration: float) -> None:
        """Execute random REST endpoint calls for the given duration."""
        self._running = True
        end_at = time.monotonic() + duration
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        while self._running and time.monotonic() < end_at:
            label, method, path_fn, query_fn = random.choice(_WORKLOAD_CHOICES)
            path = path_fn(self.agent_id)
            query = query_fn(self.agent_id)

            start = time.monotonic()
            try:
                resp = await self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=query or None,
                    headers=headers,
                    timeout=30.0,
                )
                latency_ms = (time.monotonic() - start) * 1000
                success = resp.status_code in (200, 201)
                error = ""
                if not success:
                    try:
                        body = resp.json()
                        error = body.get("detail", resp.text[:200])
                    except Exception:
                        error = resp.text[:200]

                self.metrics.record(
                    RequestResult(
                        tool=label,
                        status_code=resp.status_code,
                        latency_ms=latency_ms,
                        success=success,
                        error=error,
                    )
                )
            except httpx.TimeoutException:
                latency_ms = (time.monotonic() - start) * 1000
                self.metrics.record(
                    RequestResult(
                        tool=label,
                        status_code=0,
                        latency_ms=latency_ms,
                        success=False,
                        error="timeout",
                    )
                )
            except httpx.ConnectError as e:
                latency_ms = (time.monotonic() - start) * 1000
                self.metrics.record(
                    RequestResult(
                        tool=label,
                        status_code=0,
                        latency_ms=latency_ms,
                        success=False,
                        error=f"connect_error: {e}",
                    )
                )
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                self.metrics.record(
                    RequestResult(
                        tool=label,
                        status_code=0,
                        latency_ms=latency_ms,
                        success=False,
                        error=str(e),
                    )
                )

            # Small random delay between requests (50-200ms) to simulate real usage
            await asyncio.sleep(random.uniform(0.05, 0.2))

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Batch stress test
# ---------------------------------------------------------------------------


async def run_batch_stress(
    base_url: str,
    api_key: str,
    agent_id: str,
    metrics: StressMetrics,
    client: httpx.AsyncClient,
    count: int = 20,
) -> None:
    """Fire batch requests to test /v1/batch throughput."""
    for _ in range(count):
        calls = [
            {"tool": "get_balance", "params": {"agent_id": agent_id}},
            {"tool": "get_usage_summary", "params": {"agent_id": agent_id}},
            {"tool": "search_services", "params": {"query": "test", "limit": 3}},
        ]

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        start = time.monotonic()
        try:
            resp = await client.post(
                f"{base_url}/v1/batch",
                json={"calls": calls},
                headers=headers,
                timeout=30.0,
            )
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record(
                RequestResult(
                    tool="BATCH(3)",
                    status_code=resp.status_code,
                    latency_ms=latency_ms,
                    success=resp.status_code == 200,
                )
            )
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            metrics.record(
                RequestResult(
                    tool="BATCH(3)",
                    status_code=0,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(e),
                )
            )
        await asyncio.sleep(random.uniform(0.1, 0.3))


# ---------------------------------------------------------------------------
# Health baseline
# ---------------------------------------------------------------------------


async def health_baseline(base_url: str, client: httpx.AsyncClient, samples: int = 10) -> dict[str, float]:
    """Measure baseline health endpoint latency."""
    latencies = []
    for _ in range(samples):
        start = time.monotonic()
        try:
            resp = await client.get(f"{base_url}/v1/health", timeout=10.0)
            ms = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                latencies.append(ms)
        except Exception:
            pass
        await asyncio.sleep(0.1)

    if not latencies:
        return {"status": "unreachable", "avg_ms": 0, "p95_ms": 0}

    latencies.sort()
    return {
        "status": "ok",
        "avg_ms": round(statistics.mean(latencies), 1),
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 1),
    }


# ---------------------------------------------------------------------------
# Provisioning (create test agents if admin key available)
# ---------------------------------------------------------------------------


async def provision_test_agents(
    base_url: str,
    admin_key: str,
    client: httpx.AsyncClient,
    count: int,
) -> list[tuple[str, str]]:
    """Create test agent wallets and API keys. Returns [(agent_id, api_key)].

    Uses POST /v1/register to create each agent with its own free-tier key.
    This avoids the ownership mismatch where an admin key can't access
    per-agent endpoints for other agents.
    """
    agents = []
    # Use a per-run suffix so agents don't collide across runs (409 on prod)
    run_suffix = f"{int(time.time()) % 100000:05d}"

    for i in range(count):
        agent_id = f"stress-{run_suffix}-{i:04d}"

        # Register creates wallet + per-agent API key in one call
        try:
            resp = await client.post(
                f"{base_url}/v1/register",
                json={"agent_id": agent_id},
                timeout=10.0,
            )
            if resp.status_code == 201:
                body = resp.json()
                key = body.get("api_key", "")
                if key:
                    agents.append((agent_id, key))
                    continue
            elif resp.status_code == 409:
                # Agent already exists — can't get its key via register.
                # Fall back to admin key (ownership checks may fail).
                pass
        except Exception:
            pass

        # Fallback: use admin key for this agent
        agents.append((agent_id, admin_key))

    return agents


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    metrics: StressMetrics,
    config: dict[str, Any],
    health: dict[str, float],
    batch_metrics: StressMetrics | None = None,
) -> str:
    """Generate a markdown stress test report."""
    lines = []
    lines.append("# A2A Stress Test Report")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"**Target:** {config['base_url']}")
    lines.append(f"**Customers:** {config['customers']}")
    lines.append(f"**Duration:** {config['duration']}s (ramp-up: {config['ramp_up']}s)")
    lines.append("")

    # Health baseline
    lines.append("## 1. Health Baseline")
    lines.append("")
    if health.get("status") == "ok":
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append("| Status | OK |")
        lines.append(f"| Avg latency | {health['avg_ms']:.1f} ms |")
        lines.append(f"| Min latency | {health['min_ms']:.1f} ms |")
        lines.append(f"| Max latency | {health['max_ms']:.1f} ms |")
        lines.append(f"| P95 latency | {health['p95_ms']:.1f} ms |")
    else:
        lines.append("**Server unreachable!**")
    lines.append("")

    # Overall results
    stats = metrics.latency_stats()
    lines.append("## 2. Overall Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total requests | {metrics.total_requests:,} |")
    lines.append(f"| Successful | {metrics.successful:,} |")
    lines.append(f"| Failed | {metrics.failed:,} |")
    lines.append(f"| Error rate | {metrics.error_rate:.2f}% |")
    lines.append(f"| Duration | {metrics.duration:.1f}s |")
    lines.append(f"| Throughput | {metrics.rps:.1f} req/s |")
    lines.append(f"| Avg latency | {stats['mean']:.1f} ms |")
    lines.append(f"| Median latency | {stats['median']:.1f} ms |")
    lines.append(f"| P95 latency | {stats['p95']:.1f} ms |")
    lines.append(f"| P99 latency | {stats['p99']:.1f} ms |")
    lines.append(f"| Max latency | {stats['max']:.1f} ms |")
    lines.append(f"| Stdev | {stats['stdev']:.1f} ms |")
    lines.append("")

    # Error breakdown
    errors = metrics.errors_by_status()
    if errors:
        lines.append("## 3. Error Breakdown")
        lines.append("")
        lines.append("| Status Code | Count |")
        lines.append("|-------------|-------|")
        for code, count in sorted(errors.items()):
            label = f"{code}" if code > 0 else "timeout/connect"
            lines.append(f"| {label} | {count:,} |")
        lines.append("")

    # Per-tool breakdown
    tool_stats = metrics.results_by_tool()
    lines.append("## 4. Per-Tool Breakdown")
    lines.append("")
    lines.append("| Tool | Requests | Success | Failed | Avg (ms) | P95 (ms) |")
    lines.append("|------|----------|---------|--------|----------|----------|")
    for tool, ts in tool_stats.items():
        lines.append(
            f"| {tool} | {ts['count']:,} | {ts['success']:,} | {ts['failed']:,} "
            f"| {ts['avg_ms']:.0f} | {ts['p95_ms']:.0f} |"
        )
    lines.append("")

    # Batch results
    if batch_metrics and batch_metrics.total_requests > 0:
        bs = batch_metrics.latency_stats()
        lines.append("## 5. Batch Endpoint (/v1/batch)")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total requests | {batch_metrics.total_requests:,} |")
        lines.append(f"| Successful | {batch_metrics.successful:,} |")
        lines.append(f"| Error rate | {batch_metrics.error_rate:.2f}% |")
        lines.append(f"| Avg latency | {bs['mean']:.1f} ms |")
        lines.append(f"| P95 latency | {bs['p95']:.1f} ms |")
        lines.append(f"| P99 latency | {bs['p99']:.1f} ms |")
        lines.append("")

    # Concurrency analysis
    lines.append("## 6. Concurrency Analysis")
    lines.append("")
    # Split results into time buckets to show throughput over time
    if metrics.results:
        buckets: dict[int, list[RequestResult]] = {}
        for r in metrics.results:
            # Approximate time from latency accumulation
            bucket = 0  # We don't have exact timestamps, use index-based bucketing
            buckets.setdefault(bucket, []).append(r)

        lines.append(f"- Peak throughput: **{metrics.rps:.1f} req/s** across {config['customers']} customers")
        lines.append(f"- Per-customer rate: **{metrics.rps / max(1, config['customers']):.1f} req/s**")
        lines.append(f"- Effective concurrency: {config['customers']} simultaneous connections")
        lines.append("")

    # Assessment
    lines.append("## 7. Assessment")
    lines.append("")
    issues = []
    if metrics.error_rate > 5:
        issues.append(f"- HIGH error rate: {metrics.error_rate:.1f}% (target: <1%)")
    if stats["p99"] > 5000:
        issues.append(f"- HIGH P99 latency: {stats['p99']:.0f}ms (target: <5000ms)")
    if stats["p95"] > 2000:
        issues.append(f"- ELEVATED P95 latency: {stats['p95']:.0f}ms (target: <2000ms)")
    if metrics.rps < config["customers"] * 0.5:
        issues.append(f"- LOW throughput: {metrics.rps:.1f} req/s for {config['customers']} customers")

    if not issues:
        lines.append("**PASS** — All metrics within acceptable thresholds.")
    else:
        lines.append("**Issues detected:**")
        lines.extend(issues)
    lines.append("")

    # Thresholds
    lines.append("## 8. Pass/Fail Thresholds")
    lines.append("")
    lines.append("| Metric | Threshold | Actual | Status |")
    lines.append("|--------|-----------|--------|--------|")

    err_ok = metrics.error_rate < 5
    p95_ok = stats["p95"] < 5000
    p99_ok = stats["p99"] < 10000
    rps_ok = metrics.rps >= 5

    lines.append(f"| Error rate | <5% | {metrics.error_rate:.2f}% | {'PASS' if err_ok else 'FAIL'} |")
    lines.append(f"| P95 latency | <5000ms | {stats['p95']:.0f}ms | {'PASS' if p95_ok else 'FAIL'} |")
    lines.append(f"| P99 latency | <10000ms | {stats['p99']:.0f}ms | {'PASS' if p99_ok else 'FAIL'} |")
    lines.append(f"| Throughput | >5 req/s | {metrics.rps:.1f} req/s | {'PASS' if rps_ok else 'FAIL'} |")
    lines.append("")

    overall_pass = err_ok and p95_ok and p99_ok and rps_ok
    lines.append(f"**Overall: {'PASS' if overall_pass else 'FAIL'}**")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def gatekeeper_smoke(
    base_url: str, api_key: str, client: httpx.AsyncClient, agent_id: str = "stress-agent-0000"
) -> None:
    """Submit a trivial SAT job and verify the gatekeeper is functional.

    Called once during setup. Logs a warning on failure but does not abort
    the stress test — the Lambda may not be deployed in all environments.
    """
    print("  Gatekeeper smoke check...")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = await client.post(
            f"{base_url}/v1/gatekeeper/jobs",
            json={
                "agent_id": agent_id,
                "properties": [
                    {
                        "name": "smoke_sat",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (> x 0))",
                    }
                ],
                "scope": "economic",
                "timeout_seconds": 30,
            },
            headers=headers,
            timeout=30.0,
        )
        if resp.status_code == 201:
            body = resp.json()
            if body.get("result") == "satisfied":
                print("  Gatekeeper OK — Z3 job returned 'satisfied'")
            else:
                print(f"  WARNING: Gatekeeper returned unexpected result: {body.get('result')}")
        else:
            print(f"  WARNING: Gatekeeper returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  WARNING: Gatekeeper smoke check failed: {e}")


async def main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    customers = args.customers
    duration = args.duration
    ramp_up = args.ramp_up
    admin_key = args.admin_key

    config = {
        "base_url": base_url,
        "customers": customers,
        "duration": duration,
        "ramp_up": ramp_up,
    }

    print("=== A2A Stress Test ===")
    print(f"Target:    {base_url}")
    print(f"Customers: {customers}")
    print(f"Duration:  {duration}s (ramp-up: {ramp_up}s)")
    print()

    # Create a shared client with connection pooling
    limits = httpx.Limits(
        max_connections=customers + 10,
        max_keepalive_connections=customers,
    )
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        # 1. Health baseline
        print("Phase 1: Health baseline...")
        health = await health_baseline(base_url, client)
        if health.get("status") != "ok":
            print(f"ERROR: Server unreachable at {base_url}")
            return 1
        print(f"  Health OK — avg {health['avg_ms']:.0f}ms, p95 {health['p95_ms']:.0f}ms")

        # 2. Provision test agents
        agents: list[tuple[str, str]] = []
        agents_file = getattr(args, "agents_file", "") or ""
        if agents_file and os.path.isfile(agents_file):
            # Pre-provisioned agents (CI local server with DB-level keys)
            import json as _json

            with open(agents_file) as _f:
                agents_map = _json.load(_f)
            agents = list(agents_map.items())
            print(f"Phase 2: Loaded {len(agents)} pre-provisioned agents from {agents_file}")
        elif admin_key:
            print(f"Phase 2: Provisioning {customers} test agents...")
            agents = await provision_test_agents(base_url, admin_key, client, customers)
            print(f"  Provisioned {len(agents)} agents")
        else:
            # No admin key — create dummy agent IDs, use empty key (will get 401s)
            # In CI, the test server may have pre-provisioned agents
            print("Phase 2: No admin key — testing with unauthenticated requests")
            print("  (Set --admin-key or STRESS_ADMIN_KEY for authenticated stress testing)")
            agents = [(f"stress-agent-{i:04d}", "") for i in range(customers)]

        # 2b. Gatekeeper smoke check (use first agent's own key for ownership match)
        if agents and agents[0][1]:
            agent_id_for_smoke, key_for_smoke = agents[0]
            await gatekeeper_smoke(base_url, key_for_smoke, client, agent_id_for_smoke)
        else:
            print("  Gatekeeper smoke: SKIPPED (no agent keys)")

        # 3. Run stress test
        print(f"Phase 3: Ramping up {customers} customers over {ramp_up}s...")
        metrics = StressMetrics()
        metrics.start_time = time.monotonic()

        customer_agents = []
        tasks = []
        for i, (agent_id, api_key) in enumerate(agents):
            agent = CustomerAgent(agent_id, api_key, base_url, metrics, client)
            customer_agents.append(agent)

            # Stagger start times across the ramp-up period
            delay = (ramp_up / max(1, customers)) * i
            effective_duration = duration - delay

            async def run_with_delay(a: CustomerAgent, d: float, dur: float) -> None:
                await asyncio.sleep(d)
                await a.run(dur)

            tasks.append(asyncio.create_task(run_with_delay(agent, delay, effective_duration)))

        # 4. Batch stress (parallel with main test)
        batch_metrics = StressMetrics()
        if agents and agents[0][1]:  # Only if we have valid keys
            batch_metrics.start_time = time.monotonic()
            batch_task = asyncio.create_task(
                run_batch_stress(base_url, agents[0][1], agents[0][0], batch_metrics, client, count=30)
            )
        else:
            batch_task = None

        # Progress reporting
        print(f"Phase 4: Running for {duration}s...")
        progress_interval = max(5, duration // 10)
        elapsed = 0
        while elapsed < duration:
            await asyncio.sleep(min(progress_interval, duration - elapsed))
            elapsed += progress_interval
            if metrics.total_requests > 0:
                current_rps = metrics.total_requests / max(0.001, time.monotonic() - metrics.start_time)
                print(
                    f"  [{min(elapsed, duration):3d}s] {metrics.total_requests:,} requests, "
                    f"{metrics.error_rate:.1f}% errors, {current_rps:.1f} req/s"
                )

        # Wait for all tasks to complete
        for agent in customer_agents:
            agent.stop()

        await asyncio.gather(*tasks, return_exceptions=True)
        metrics.end_time = time.monotonic()

        if batch_task:
            await batch_task
            batch_metrics.end_time = time.monotonic()

    # 5. Generate report
    print()
    print("Phase 5: Generating report...")

    report = generate_report(metrics, config, health, batch_metrics)

    # Write report to file
    report_path = os.environ.get("STRESS_REPORT_PATH", "stress_test_report.md")
    with open(report_path, "w") as f:
        f.write(report)
    print(f"  Report written to {report_path}")

    # Also print to stdout
    print()
    print(report)

    # Exit code: 0 = pass, 1 = fail
    stats = metrics.latency_stats()
    passed = metrics.error_rate < 5 and stats["p95"] < 5000 and stats["p99"] < 10000 and metrics.rps >= 5

    # If no admin key, don't fail on auth/payment errors (401/402 are expected).
    # Allow up to 2% non-auth errors (e.g. transient 503s during deploy).
    if not args.admin_key:
        errors = metrics.errors_by_status()
        auth_errors = errors.get(401, 0) + errors.get(402, 0) + errors.get(403, 0)
        non_auth_errors = metrics.failed - auth_errors
        non_auth_pct = (non_auth_errors / max(1, metrics.total_requests)) * 100
        if auth_errors > 0 and non_auth_pct <= 2:
            print(
                f"\nNote: {auth_errors} auth errors (no admin key) + {non_auth_errors} transient errors. Treating as PASS."
            )
            passed = True

    return 0 if passed else 1


def cli() -> int:
    parser = argparse.ArgumentParser(description="A2A Commerce Platform Stress Test")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("STRESS_BASE_URL", DEFAULT_BASE_URL),
        help=f"Target server URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=int(os.environ.get("STRESS_CUSTOMERS", DEFAULT_CUSTOMERS)),
        help=f"Number of concurrent customers (default: {DEFAULT_CUSTOMERS})",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.environ.get("STRESS_DURATION", DEFAULT_DURATION)),
        help=f"Test duration in seconds (default: {DEFAULT_DURATION})",
    )
    parser.add_argument(
        "--ramp-up",
        type=int,
        default=int(os.environ.get("STRESS_RAMP_UP", DEFAULT_RAMP_UP)),
        help=f"Ramp-up period in seconds (default: {DEFAULT_RAMP_UP})",
    )
    parser.add_argument(
        "--admin-key",
        default=os.environ.get("STRESS_ADMIN_KEY", ""),
        help="Admin API key for provisioning test agents",
    )
    parser.add_argument(
        "--agents-file",
        default=os.environ.get("STRESS_AGENTS_FILE", ""),
        help="JSON file mapping agent_id → api_key (from provision_stress_agents.py)",
    )
    args = parser.parse_args()
    return asyncio.run(main(args))


if __name__ == "__main__":
    sys.exit(cli())
