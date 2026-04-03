#!/usr/bin/env python3
"""
A2A Commerce Platform — Long-Duration Performance Stress Test
==============================================================

Runs a sustained load test for hours, collecting periodic metric snapshots
from both the client side (latency, throughput, errors) and the server side
(Prometheus /v1/metrics endpoint).

Designed to be left unattended for 1-3+ hours.

Usage:
    python scripts/stress_test_long.py \
        --base-url https://api.greenhelix.net \
        --duration 10800 \
        --customers 15 \
        --snapshot-interval 60 \
        --admin-key sk_admin_... \
        --report-path reports/perf-report.md

Environment variables:
    STRESS_BASE_URL         Target server URL
    STRESS_ADMIN_KEY        Admin API key for provisioning
    STRESS_CUSTOMERS        Concurrent customers (default: 15)
    STRESS_DURATION         Duration in seconds (default: 10800 = 3hrs)
    STRESS_SNAPSHOT_INTERVAL Seconds between metric snapshots (default: 60)
    STRESS_REPORT_PATH      Report output path
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

DEFAULT_BASE_URL = "https://api.greenhelix.net"
DEFAULT_CUSTOMERS = 15
DEFAULT_DURATION = 10800  # 3 hours
DEFAULT_SNAPSHOT_INTERVAL = 60  # 1 minute
DEFAULT_REPORT_PATH = "reports/stress-test-long-report.md"

# Workload mix: (weight, label, method, path_fn, query_fn, body_fn)
# Includes both read and write operations for realistic mix
WORKLOADS: list[tuple[int, str, str, Any, Any, Any]] = [
    # Read-heavy (70%)
    (25, "get_balance", "GET", lambda aid: f"/v1/billing/wallets/{aid}/balance", lambda _: {}, None),
    (12, "get_usage_summary", "GET", lambda aid: f"/v1/billing/wallets/{aid}/usage", lambda _: {}, None),
    (8, "search_services", "GET", lambda _: "/v1/marketplace/services", lambda _: {"query": "test", "limit": 5}, None),
    (6, "get_events", "GET", lambda _: "/v1/infra/events", lambda _: {"limit": 10}, None),
    (5, "list_webhooks", "GET", lambda _: "/v1/infra/webhooks", lambda _: {}, None),
    (4, "get_leaderboard", "GET", lambda _: "/v1/billing/leaderboard", lambda _: {"metric": "calls", "limit": 5}, None),
    (4, "estimate_cost", "GET", lambda _: "/v1/billing/estimate", lambda _: {"tool_name": "get_balance", "quantity": 10}, None),
    (3, "get_timeseries", "GET", lambda aid: f"/v1/billing/wallets/{aid}/timeseries", lambda _: {"interval": "hour"}, None),
    (3, "get_health", "GET", lambda _: "/v1/health", lambda _: {}, None),
    # Write operations (15%)
    (5, "deposit_small", "POST", lambda aid: f"/v1/billing/wallets/{aid}/deposit", lambda _: {}, lambda: {"amount": "0.01"}),
    (3, "create_intent", "POST", lambda _: "/v1/payments/intents", lambda _: {}, None),  # needs special handling
    (3, "get_pricing", "GET", lambda _: "/v1/pricing", lambda _: {}, None),
    (2, "get_payment_history", "GET", lambda _: "/v1/payments/history", lambda aid: {"agent_id": aid, "limit": 5}, None),
    (2, "list_subscriptions", "GET", lambda _: "/v1/payments/subscriptions", lambda aid: {"agent_id": aid, "limit": 5}, None),
    # Marketplace (5%)
    (3, "trust_servers", "GET", lambda _: "/v1/trust/servers", lambda _: {"limit": 3}, None),
    (2, "marketplace_match", "GET", lambda _: "/v1/marketplace/match", lambda _: {"query": "analysis"}, None),
]

# Build weighted selection list
_CHOICES: list[tuple[str, str, Any, Any, Any]] = []
for weight, label, method, path_fn, query_fn, body_fn in WORKLOADS:
    _CHOICES.extend([(label, method, path_fn, query_fn, body_fn)] * weight)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class RequestSample:
    tool: str
    status_code: int
    latency_ms: float
    success: bool
    timestamp: float
    error: str = ""


@dataclass
class SnapshotMetrics:
    """Metrics for a single time window."""
    window_start: float
    window_end: float
    samples: list[RequestSample] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.samples)

    @property
    def successful(self) -> int:
        return sum(1 for s in self.samples if s.success)

    @property
    def error_rate(self) -> float:
        return (self.total - self.successful) / max(1, self.total) * 100

    @property
    def rps(self) -> float:
        dur = self.window_end - self.window_start
        return self.total / max(0.001, dur)

    def latency_stats(self) -> dict[str, float]:
        lats = sorted(s.latency_ms for s in self.samples)
        if not lats:
            return {"min": 0, "max": 0, "mean": 0, "median": 0, "p50": 0, "p95": 0, "p99": 0, "stdev": 0}
        return {
            "min": lats[0],
            "max": lats[-1],
            "mean": statistics.mean(lats),
            "median": statistics.median(lats),
            "p50": lats[len(lats) // 2],
            "p95": lats[int(len(lats) * 0.95)],
            "p99": lats[int(len(lats) * 0.99)],
            "stdev": statistics.stdev(lats) if len(lats) > 1 else 0,
        }

    def errors_by_status(self) -> dict[int, int]:
        c: dict[int, int] = {}
        for s in self.samples:
            if not s.success:
                c[s.status_code] = c.get(s.status_code, 0) + 1
        return c

    def by_tool(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[RequestSample]] = {}
        for s in self.samples:
            groups.setdefault(s.tool, []).append(s)
        out = {}
        for tool, samples in sorted(groups.items()):
            lats = [s.latency_ms for s in samples]
            out[tool] = {
                "count": len(samples),
                "success": sum(1 for s in samples if s.success),
                "failed": sum(1 for s in samples if not s.success),
                "avg_ms": statistics.mean(lats),
                "p95_ms": sorted(lats)[int(len(lats) * 0.95)] if lats else 0,
            }
        return out


@dataclass
class LongRunMetrics:
    """Accumulates all samples and snapshots."""
    all_samples: list[RequestSample] = field(default_factory=list)
    snapshots: list[SnapshotMetrics] = field(default_factory=list)
    server_metrics_snapshots: list[dict[str, Any]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _current_window_samples: list[RequestSample] = field(default_factory=list)

    async def record(self, sample: RequestSample) -> None:
        async with self._lock:
            self.all_samples.append(sample)
            self._current_window_samples.append(sample)

    async def take_snapshot(self, window_start: float, window_end: float) -> SnapshotMetrics:
        async with self._lock:
            snap = SnapshotMetrics(
                window_start=window_start,
                window_end=window_end,
                samples=list(self._current_window_samples),
            )
            self._current_window_samples = []
        self.snapshots.append(snap)
        return snap


# ---------------------------------------------------------------------------
# Server metrics scraper
# ---------------------------------------------------------------------------


async def scrape_server_metrics(base_url: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Scrape /v1/metrics and parse Prometheus text format."""
    try:
        resp = await client.get(f"{base_url}/v1/metrics", timeout=10.0)
        if resp.status_code != 200:
            return {"error": f"status {resp.status_code}", "timestamp": time.time()}

        data: dict[str, Any] = {"timestamp": time.time(), "raw_lines": 0}
        for line in resp.text.strip().split("\n"):
            if line.startswith("#"):
                continue
            data["raw_lines"] += 1
            parts = line.split(" ", 1)
            if len(parts) == 2:
                key, val = parts
                try:
                    data[key] = float(val)
                except ValueError:
                    data[key] = val
        return data
    except Exception as e:
        return {"error": str(e), "timestamp": time.time()}


# ---------------------------------------------------------------------------
# Customer agent
# ---------------------------------------------------------------------------


class StressAgent:
    def __init__(
        self,
        agent_id: str,
        api_key: str,
        peer_id: str,
        base_url: str,
        metrics: LongRunMetrics,
        client: httpx.AsyncClient,
    ) -> None:
        self.agent_id = agent_id
        self.api_key = api_key
        self.peer_id = peer_id
        self.base_url = base_url
        self.metrics = metrics
        self.client = client
        self._running = False

    async def run(self, duration: float) -> None:
        self._running = True
        end_at = time.monotonic() + duration
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

        while self._running and time.monotonic() < end_at:
            label, method, path_fn, query_fn, body_fn = random.choice(_CHOICES)
            path = path_fn(self.agent_id)
            query = query_fn(self.agent_id) if query_fn else {}
            body = None

            # Special handling for create_intent (needs payer/payee)
            if label == "create_intent":
                body = {
                    "payer": self.agent_id,
                    "payee": self.peer_id,
                    "amount": "0.01",
                    "description": "stress test",
                }
            elif body_fn:
                body = body_fn()

            start = time.monotonic()
            ts = time.time()
            try:
                kwargs: dict[str, Any] = {
                    "method": method,
                    "url": f"{self.base_url}{path}",
                    "headers": headers,
                    "timeout": 30.0,
                }
                if query:
                    kwargs["params"] = query
                if body:
                    kwargs["json"] = body

                resp = await self.client.request(**kwargs)
                latency_ms = (time.monotonic() - start) * 1000
                success = resp.status_code in (200, 201)
                error = ""
                if not success:
                    try:
                        error = resp.json().get("detail", resp.text[:200])
                    except Exception:
                        error = resp.text[:200]

                await self.metrics.record(RequestSample(
                    tool=label, status_code=resp.status_code,
                    latency_ms=latency_ms, success=success,
                    timestamp=ts, error=error,
                ))
            except httpx.TimeoutException:
                latency_ms = (time.monotonic() - start) * 1000
                await self.metrics.record(RequestSample(
                    tool=label, status_code=0, latency_ms=latency_ms,
                    success=False, timestamp=ts, error="timeout",
                ))
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                await self.metrics.record(RequestSample(
                    tool=label, status_code=0, latency_ms=latency_ms,
                    success=False, timestamp=ts, error=str(e)[:200],
                ))

            # Random delay: 50-300ms between requests per agent
            await asyncio.sleep(random.uniform(0.05, 0.3))

    def stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


async def provision_agents(
    base_url: str, client: httpx.AsyncClient, count: int,
) -> list[tuple[str, str]]:
    """Register test agents via public endpoint. Returns [(agent_id, api_key)].

    Retries with backoff on 503 (Cloudflare throttling).
    Adds delay between registrations to avoid rate limiting.
    """
    agents = []
    ts = int(time.time())
    for i in range(count):
        success = False
        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{base_url}/v1/register",
                    json={"agent_id": f"perf-agent-{ts}-{i:03d}"},
                    timeout=15.0,
                )
                if resp.status_code in (200, 201):
                    body = resp.json()
                    agents.append((body["agent_id"], body["api_key"]))
                    success = True
                    break
                elif resp.status_code == 503:
                    wait = (attempt + 1) * 3
                    print(f"  Registration {i}: 503, retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    print(f"  Warning: registration {i} returned {resp.status_code}")
                    break
            except Exception as e:
                print(f"  Warning: registration {i} failed: {e}")
                break
        if not success and i < count:
            await asyncio.sleep(1)  # Brief pause between agents
        else:
            await asyncio.sleep(0.5)  # Normal pacing
    return agents


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_long_report(
    metrics: LongRunMetrics,
    config: dict[str, Any],
    health_baseline: dict[str, float],
) -> str:
    """Generate comprehensive performance report."""
    lines: list[str] = []
    all_samples = metrics.all_samples
    snapshots = metrics.snapshots
    server_snaps = metrics.server_metrics_snapshots

    total_duration = config["duration"]
    actual_duration = (all_samples[-1].timestamp - all_samples[0].timestamp) if len(all_samples) > 1 else total_duration

    lines.append("# A2A Performance Stress Test Report")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append(f"**Target:** {config['base_url']}")
    lines.append(f"**Duration:** {actual_duration:.0f}s ({actual_duration/3600:.1f} hours)")
    lines.append(f"**Concurrent Agents:** {config['customers']}")
    lines.append(f"**Snapshot Interval:** {config['snapshot_interval']}s")
    lines.append(f"**Total Requests:** {len(all_samples):,}")
    lines.append("")

    # --- 1. Health Baseline ---
    lines.append("## 1. Health Baseline (Pre-Test)")
    lines.append("")
    if health_baseline.get("status") == "ok":
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for k, v in health_baseline.items():
            if k != "status":
                lines.append(f"| {k} | {v:.1f} ms |" if isinstance(v, float) else f"| {k} | {v} |")
    else:
        lines.append("**Server unreachable during baseline!**")
    lines.append("")

    # --- 2. Overall Results ---
    all_lats = sorted(s.latency_ms for s in all_samples)
    total_ok = sum(1 for s in all_samples if s.success)
    total_err = len(all_samples) - total_ok
    err_rate = total_err / max(1, len(all_samples)) * 100
    overall_rps = len(all_samples) / max(0.001, actual_duration)

    stats = {
        "min": all_lats[0] if all_lats else 0,
        "max": all_lats[-1] if all_lats else 0,
        "mean": statistics.mean(all_lats) if all_lats else 0,
        "median": statistics.median(all_lats) if all_lats else 0,
        "p50": all_lats[len(all_lats) // 2] if all_lats else 0,
        "p95": all_lats[int(len(all_lats) * 0.95)] if all_lats else 0,
        "p99": all_lats[int(len(all_lats) * 0.99)] if all_lats else 0,
        "stdev": statistics.stdev(all_lats) if len(all_lats) > 1 else 0,
    }

    lines.append("## 2. Aggregate Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total requests | {len(all_samples):,} |")
    lines.append(f"| Successful | {total_ok:,} |")
    lines.append(f"| Failed | {total_err:,} |")
    lines.append(f"| Error rate | {err_rate:.2f}% |")
    lines.append(f"| Duration | {actual_duration:.0f}s ({actual_duration/3600:.1f}h) |")
    lines.append(f"| Avg throughput | {overall_rps:.1f} req/s |")
    lines.append(f"| Min latency | {stats['min']:.1f} ms |")
    lines.append(f"| Mean latency | {stats['mean']:.1f} ms |")
    lines.append(f"| Median (p50) | {stats['p50']:.1f} ms |")
    lines.append(f"| P95 latency | {stats['p95']:.1f} ms |")
    lines.append(f"| P99 latency | {stats['p99']:.1f} ms |")
    lines.append(f"| Max latency | {stats['max']:.1f} ms |")
    lines.append(f"| Stdev | {stats['stdev']:.1f} ms |")
    lines.append("")

    # --- 3. Error Breakdown ---
    err_counts: dict[int, int] = {}
    for s in all_samples:
        if not s.success:
            err_counts[s.status_code] = err_counts.get(s.status_code, 0) + 1
    if err_counts:
        lines.append("## 3. Error Breakdown")
        lines.append("")
        lines.append("| Status Code | Count | % of Total |")
        lines.append("|-------------|-------|------------|")
        for code, cnt in sorted(err_counts.items()):
            label = f"{code}" if code > 0 else "timeout/connect"
            pct = cnt / len(all_samples) * 100
            lines.append(f"| {label} | {cnt:,} | {pct:.2f}% |")
        lines.append("")

    # --- 4. Per-Tool Breakdown ---
    tool_groups: dict[str, list[RequestSample]] = {}
    for s in all_samples:
        tool_groups.setdefault(s.tool, []).append(s)

    lines.append("## 4. Per-Endpoint Breakdown")
    lines.append("")
    lines.append("| Endpoint | Requests | Success | Failed | Avg (ms) | P95 (ms) | P99 (ms) |")
    lines.append("|----------|----------|---------|--------|----------|----------|----------|")
    for tool, samples in sorted(tool_groups.items()):
        lats = sorted(s.latency_ms for s in samples)
        ok = sum(1 for s in samples if s.success)
        fail = len(samples) - ok
        avg = statistics.mean(lats) if lats else 0
        p95 = lats[int(len(lats) * 0.95)] if lats else 0
        p99 = lats[int(len(lats) * 0.99)] if lats else 0
        lines.append(f"| {tool} | {len(samples):,} | {ok:,} | {fail:,} | {avg:.0f} | {p95:.0f} | {p99:.0f} |")
    lines.append("")

    # --- 5. Time-Series Performance (periodic snapshots) ---
    if snapshots:
        lines.append("## 5. Performance Over Time")
        lines.append("")
        lines.append("Each row represents a 1-minute window.")
        lines.append("")
        lines.append("| Time (min) | Requests | RPS | Err% | Avg (ms) | P95 (ms) | P99 (ms) |")
        lines.append("|------------|----------|-----|------|----------|----------|----------|")

        test_start = snapshots[0].window_start if snapshots else 0
        for i, snap in enumerate(snapshots):
            minute = (snap.window_start - test_start) / 60
            st = snap.latency_stats()
            lines.append(
                f"| {minute:.0f} | {snap.total:,} | {snap.rps:.1f} | {snap.error_rate:.1f}% "
                f"| {st['mean']:.0f} | {st['p95']:.0f} | {st['p99']:.0f} |"
            )
        lines.append("")

        # RPS trend analysis
        if len(snapshots) > 10:
            first_10 = [s.rps for s in snapshots[:10]]
            last_10 = [s.rps for s in snapshots[-10:]]
            first_avg = statistics.mean(first_10)
            last_avg = statistics.mean(last_10)
            drift = ((last_avg - first_avg) / max(0.001, first_avg)) * 100

            lines.append("### Throughput Trend")
            lines.append("")
            lines.append(f"- First 10 minutes avg RPS: **{first_avg:.1f}**")
            lines.append(f"- Last 10 minutes avg RPS: **{last_avg:.1f}**")
            lines.append(f"- Drift: **{drift:+.1f}%**")
            if abs(drift) < 10:
                lines.append("- Assessment: **Stable** — throughput consistent over time")
            elif drift < -10:
                lines.append("- Assessment: **Degrading** — throughput declining over time (possible resource exhaustion)")
            else:
                lines.append("- Assessment: **Improving** — throughput increasing (likely cache warming)")
            lines.append("")

        # Latency trend
        if len(snapshots) > 10:
            first_p95 = [s.latency_stats()["p95"] for s in snapshots[:10]]
            last_p95 = [s.latency_stats()["p95"] for s in snapshots[-10:]]
            lines.append("### Latency Trend (P95)")
            lines.append("")
            lines.append(f"- First 10 min avg P95: **{statistics.mean(first_p95):.0f} ms**")
            lines.append(f"- Last 10 min avg P95: **{statistics.mean(last_p95):.0f} ms**")
            p95_drift = ((statistics.mean(last_p95) - statistics.mean(first_p95)) / max(0.001, statistics.mean(first_p95))) * 100
            lines.append(f"- Drift: **{p95_drift:+.1f}%**")
            if p95_drift > 20:
                lines.append("- Assessment: **Latency creep detected** — P95 increasing over time")
            elif p95_drift < -10:
                lines.append("- Assessment: **Improving** — latency decreasing (cache warming)")
            else:
                lines.append("- Assessment: **Stable** — latency consistent")
            lines.append("")

        # Error rate trend
        if len(snapshots) > 10:
            first_err = [s.error_rate for s in snapshots[:10]]
            last_err = [s.error_rate for s in snapshots[-10:]]
            lines.append("### Error Rate Trend")
            lines.append("")
            lines.append(f"- First 10 min avg error rate: **{statistics.mean(first_err):.2f}%**")
            lines.append(f"- Last 10 min avg error rate: **{statistics.mean(last_err):.2f}%**")
            if statistics.mean(last_err) > statistics.mean(first_err) + 2:
                lines.append("- Assessment: **Error rate increasing** — possible resource exhaustion")
            else:
                lines.append("- Assessment: **Stable**")
            lines.append("")

    # --- 6. Server-Side Metrics (Prometheus) ---
    if server_snaps and len(server_snaps) > 1:
        lines.append("## 6. Server-Side Metrics (Prometheus)")
        lines.append("")

        first_srv = server_snaps[0]
        last_srv = server_snaps[-1]

        # Total requests delta
        if "a2a_requests_total" in first_srv and "a2a_requests_total" in last_srv:
            req_delta = last_srv["a2a_requests_total"] - first_srv["a2a_requests_total"]
            err_delta = last_srv.get("a2a_errors_total", 0) - first_srv.get("a2a_errors_total", 0)
            time_delta = last_srv["timestamp"] - first_srv["timestamp"]
            srv_rps = req_delta / max(0.001, time_delta)
            srv_err_rate = err_delta / max(1, req_delta) * 100

            lines.append("| Server Metric | Value |")
            lines.append("|---------------|-------|")
            lines.append(f"| Requests processed (server-side) | {req_delta:,.0f} |")
            lines.append(f"| Errors (server-side) | {err_delta:,.0f} |")
            lines.append(f"| Server error rate | {srv_err_rate:.2f}% |")
            lines.append(f"| Server avg RPS | {srv_rps:.1f} |")

            # Duration stats from server
            dur_count_delta = last_srv.get("a2a_request_duration_ms_count", 0) - first_srv.get("a2a_request_duration_ms_count", 0)
            dur_sum_delta = last_srv.get("a2a_request_duration_ms_sum", 0) - first_srv.get("a2a_request_duration_ms_sum", 0)
            if dur_count_delta > 0:
                srv_avg_ms = dur_sum_delta / dur_count_delta
                lines.append(f"| Server avg latency | {srv_avg_ms:.1f} ms |")
            lines.append("")

        # Per-tool server-side counts (delta)
        first_tools: dict[str, float] = {}
        last_tools: dict[str, float] = {}
        for key, val in first_srv.items():
            if key.startswith("a2a_requests_by_tool_total"):
                tool_name = key.split('"')[1] if '"' in key else key
                first_tools[tool_name] = val
        for key, val in last_srv.items():
            if key.startswith("a2a_requests_by_tool_total"):
                tool_name = key.split('"')[1] if '"' in key else key
                last_tools[tool_name] = val

        if last_tools:
            lines.append("### Server Per-Tool Counts (delta)")
            lines.append("")
            lines.append("| Tool | Requests |")
            lines.append("|------|----------|")
            for tool in sorted(last_tools.keys()):
                delta = last_tools[tool] - first_tools.get(tool, 0)
                if delta > 0:
                    lines.append(f"| {tool} | {delta:,.0f} |")
            lines.append("")

        # Server metrics time series
        if len(server_snaps) > 2:
            lines.append("### Server Metrics Over Time")
            lines.append("")
            lines.append("| Time (min) | Total Reqs | Errors | Avg Latency (ms) |")
            lines.append("|------------|------------|--------|-------------------|")
            base_ts = server_snaps[0]["timestamp"]
            prev = server_snaps[0]
            for snap in server_snaps[1:]:
                minute = (snap["timestamp"] - base_ts) / 60
                req_d = snap.get("a2a_requests_total", 0) - prev.get("a2a_requests_total", 0)
                err_d = snap.get("a2a_errors_total", 0) - prev.get("a2a_errors_total", 0)
                dur_c = snap.get("a2a_request_duration_ms_count", 0) - prev.get("a2a_request_duration_ms_count", 0)
                dur_s = snap.get("a2a_request_duration_ms_sum", 0) - prev.get("a2a_request_duration_ms_sum", 0)
                avg_lat = dur_s / max(1, dur_c)
                lines.append(f"| {minute:.0f} | {req_d:,.0f} | {err_d:,.0f} | {avg_lat:.0f} |")
                prev = snap
            lines.append("")

    # --- 7. Stability Analysis ---
    lines.append("## 7. Stability Analysis")
    lines.append("")

    if snapshots:
        rps_values = [s.rps for s in snapshots if s.total > 0]
        p95_values = [s.latency_stats()["p95"] for s in snapshots if s.total > 0]
        err_values = [s.error_rate for s in snapshots]

        if rps_values:
            rps_cv = (statistics.stdev(rps_values) / max(0.001, statistics.mean(rps_values)) * 100) if len(rps_values) > 1 else 0
            lines.append(f"- **Throughput stability (CV):** {rps_cv:.1f}% — {'Stable (<15%)' if rps_cv < 15 else 'Variable (>15%)'}")
        if p95_values:
            p95_cv = (statistics.stdev(p95_values) / max(0.001, statistics.mean(p95_values)) * 100) if len(p95_values) > 1 else 0
            lines.append(f"- **Latency stability (CV):** {p95_cv:.1f}% — {'Stable (<20%)' if p95_cv < 20 else 'Variable (>20%)'}")

        # Detect outlier windows
        if p95_values and len(p95_values) > 5:
            p95_mean = statistics.mean(p95_values)
            p95_std = statistics.stdev(p95_values) if len(p95_values) > 1 else 0
            outliers = [i for i, v in enumerate(p95_values) if v > p95_mean + 3 * p95_std]
            if outliers:
                lines.append(f"- **Latency spikes:** {len(outliers)} windows with P95 > 3σ from mean")
                for idx in outliers[:5]:
                    lines.append(f"  - Minute {idx}: P95 = {p95_values[idx]:.0f} ms")
            else:
                lines.append("- **Latency spikes:** None detected (no windows > 3σ)")

        # Memory leak indicator: monotonically increasing latency
        if len(p95_values) > 20:
            chunks = [p95_values[i:i+10] for i in range(0, len(p95_values)-9, 10)]
            chunk_avgs = [statistics.mean(c) for c in chunks]
            increasing = all(chunk_avgs[i] <= chunk_avgs[i+1] * 1.05 for i in range(len(chunk_avgs)-1))
            if increasing and len(chunk_avgs) > 2 and chunk_avgs[-1] > chunk_avgs[0] * 1.3:
                lines.append("- **Possible resource leak:** Latency consistently increasing over test duration")
            else:
                lines.append("- **Resource leak indicator:** No monotonic latency increase detected")
    lines.append("")

    # --- 8. Pass/Fail Assessment ---
    lines.append("## 8. Pass/Fail Assessment")
    lines.append("")
    lines.append("| Metric | Threshold | Actual | Status |")
    lines.append("|--------|-----------|--------|--------|")

    err_ok = err_rate < 5
    p95_ok = stats["p95"] < 5000
    p99_ok = stats["p99"] < 10000
    rps_ok = overall_rps >= 5
    stability_ok = True
    if snapshots and len(snapshots) > 10:
        last_10_err = statistics.mean([s.error_rate for s in snapshots[-10:]])
        stability_ok = last_10_err < 10

    lines.append(f"| Error rate | <5% | {err_rate:.2f}% | {'PASS' if err_ok else 'FAIL'} |")
    lines.append(f"| P95 latency | <5000ms | {stats['p95']:.0f}ms | {'PASS' if p95_ok else 'FAIL'} |")
    lines.append(f"| P99 latency | <10000ms | {stats['p99']:.0f}ms | {'PASS' if p99_ok else 'FAIL'} |")
    lines.append(f"| Throughput | >5 req/s | {overall_rps:.1f} req/s | {'PASS' if rps_ok else 'FAIL'} |")
    lines.append(f"| Late-test stability | err <10% last 10min | {'OK' if stability_ok else 'DEGRADED'} | {'PASS' if stability_ok else 'FAIL'} |")
    lines.append("")

    overall = err_ok and p95_ok and p99_ok and rps_ok and stability_ok
    lines.append(f"**Overall: {'PASS' if overall else 'FAIL'}**")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Health baseline
# ---------------------------------------------------------------------------


async def measure_health_baseline(base_url: str, client: httpx.AsyncClient, samples: int = 20) -> dict[str, float]:
    # First, wait for rate limit to clear if needed
    for attempt in range(60):  # Up to 60 minutes of waiting
        try:
            resp = await client.get(f"{base_url}/v1/health", timeout=10.0)
            if resp.status_code == 200:
                break
            elif resp.status_code == 429:
                reset = int(resp.headers.get("x-ratelimit-reset", "60"))
                wait = min(reset, 120)  # Wait up to 2 min at a time
                print(f"  Rate limited (429). Reset in {reset}s, waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                break
        except Exception:
            await asyncio.sleep(5)

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
        await asyncio.sleep(0.5)

    if not latencies:
        return {"status": "unreachable"}

    latencies.sort()
    return {
        "status": "ok",
        "avg_ms": round(statistics.mean(latencies), 1),
        "min_ms": round(min(latencies), 1),
        "max_ms": round(max(latencies), 1),
        "p50_ms": round(latencies[len(latencies) // 2], 1),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)], 1),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")
    customers = args.customers
    duration = args.duration
    snapshot_interval = args.snapshot_interval

    config = {
        "base_url": base_url,
        "customers": customers,
        "duration": duration,
        "snapshot_interval": snapshot_interval,
    }

    hours = duration / 3600
    print("=" * 60)
    print("  A2A Long-Duration Performance Stress Test")
    print("=" * 60)
    print(f"  Target:      {base_url}")
    print(f"  Customers:   {customers}")
    print(f"  Duration:    {duration}s ({hours:.1f} hours)")
    print(f"  Snapshots:   every {snapshot_interval}s")
    print(f"  Report:      {args.report_path}")
    print("=" * 60)
    print()

    limits = httpx.Limits(max_connections=customers + 10, max_keepalive_connections=customers)

    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        # 1. Health baseline
        print("[1/5] Measuring health baseline...")
        health = await measure_health_baseline(base_url, client)
        if health.get("status") != "ok":
            print(f"  ERROR: Server unreachable at {base_url}")
            return 1
        print(f"  OK — avg {health['avg_ms']:.0f}ms, p95 {health['p95_ms']:.0f}ms")

        # 2. Provision agents (pairs for payment intents)
        print(f"[2/5] Provisioning {customers} test agents...")
        agents = await provision_agents(base_url, client, customers)
        if len(agents) < 2:
            print("  ERROR: Need at least 2 agents")
            return 1
        print(f"  Provisioned {len(agents)} agents")

        # 3. Initial server metrics
        print("[3/5] Scraping initial server metrics...")
        metrics = LongRunMetrics()
        initial_server = await scrape_server_metrics(base_url, client)
        if "error" not in initial_server:
            metrics.server_metrics_snapshots.append(initial_server)
            print(f"  Server: {initial_server.get('a2a_requests_total', 'N/A')} total requests so far")
        else:
            print(f"  Warning: Cannot scrape server metrics ({initial_server.get('error', '')})")
            print("  (This is expected if /v1/metrics is IP-restricted. Client-side metrics still collected.)")

        # 4. Run the stress test
        actual_customers = len(agents)
        config["customers"] = actual_customers  # Update to reflect actual
        print(f"[4/5] Starting {actual_customers} agents for {hours:.1f} hours...")
        print(f"  Progress updates every {snapshot_interval}s")
        print()

        # Create agent pairs
        stress_agents = []
        tasks = []
        for i, (agent_id, api_key) in enumerate(agents):
            peer_id = agents[(i + 1) % len(agents)][0]
            agent = StressAgent(agent_id, api_key, peer_id, base_url, metrics, client)
            stress_agents.append(agent)

            # Stagger startup over 30s
            delay = (30 / max(1, actual_customers)) * i

            async def _run(a: StressAgent, d: float) -> None:
                await asyncio.sleep(d)
                await a.run(duration - d)

            tasks.append(asyncio.create_task(_run(agent, delay)))

        # Snapshot loop
        test_start = time.monotonic()
        window_start = test_start
        snapshot_count = 0

        while time.monotonic() - test_start < duration:
            await asyncio.sleep(min(snapshot_interval, duration - (time.monotonic() - test_start)))
            now = time.monotonic()

            # Take client-side snapshot
            snap = await metrics.take_snapshot(window_start, now)
            window_start = now
            snapshot_count += 1

            # Scrape server metrics
            server_snap = await scrape_server_metrics(base_url, client)
            if "error" not in server_snap:
                metrics.server_metrics_snapshots.append(server_snap)

            # Progress output
            elapsed_min = (now - test_start) / 60
            total_reqs = len(metrics.all_samples)
            total_rps = total_reqs / max(0.001, now - test_start)
            print(
                f"  [{elapsed_min:5.0f}m / {hours*60:.0f}m] "
                f"reqs={total_reqs:,}  rps={total_rps:.1f}  "
                f"window: {snap.total} reqs, {snap.error_rate:.1f}% err, "
                f"avg={snap.latency_stats()['mean']:.0f}ms p95={snap.latency_stats()['p95']:.0f}ms"
            )

        # Stop all agents
        for agent in stress_agents:
            agent.stop()
        await asyncio.gather(*tasks, return_exceptions=True)

        # Final server metrics
        final_server = await scrape_server_metrics(base_url, client)
        if "error" not in final_server:
            metrics.server_metrics_snapshots.append(final_server)

    # 5. Generate report
    print()
    print("[5/5] Generating report...")

    report = generate_long_report(metrics, config, health)

    # Write report
    report_dir = os.path.dirname(args.report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
    with open(args.report_path, "w") as f:
        f.write(report)
    print(f"  Report written to {args.report_path}")

    # Also save raw snapshot data as JSON for further analysis
    json_path = args.report_path.replace(".md", ".json")
    snapshot_data = []
    for snap in metrics.snapshots:
        st = snap.latency_stats()
        snapshot_data.append({
            "window_start": snap.window_start,
            "total": snap.total,
            "rps": round(snap.rps, 2),
            "error_rate": round(snap.error_rate, 2),
            "avg_ms": round(st["mean"], 1),
            "p95_ms": round(st["p95"], 1),
            "p99_ms": round(st["p99"], 1),
        })
    with open(json_path, "w") as f:
        json.dump({
            "config": config,
            "health_baseline": health,
            "snapshots": snapshot_data,
            "server_metrics": metrics.server_metrics_snapshots,
        }, f, indent=2, default=str)
    print(f"  Raw data written to {json_path}")

    print()
    print(report)
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description="A2A Long-Duration Performance Stress Test")
    parser.add_argument("--base-url", default=os.environ.get("STRESS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--customers", type=int, default=int(os.environ.get("STRESS_CUSTOMERS", DEFAULT_CUSTOMERS)))
    parser.add_argument("--duration", type=int, default=int(os.environ.get("STRESS_DURATION", DEFAULT_DURATION)))
    parser.add_argument("--snapshot-interval", type=int, default=int(os.environ.get("STRESS_SNAPSHOT_INTERVAL", DEFAULT_SNAPSHOT_INTERVAL)))
    parser.add_argument("--report-path", default=os.environ.get("STRESS_REPORT_PATH", DEFAULT_REPORT_PATH))
    parser.add_argument("--admin-key", default=os.environ.get("STRESS_ADMIN_KEY", ""))
    args = parser.parse_args()
    return asyncio.run(main(args))


if __name__ == "__main__":
    sys.exit(cli())
