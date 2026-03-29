"""Score computation engine for trust & reputation.

Pure functions that take probe results + security scans as input and produce
trust scores as output. No I/O — easy to test deterministically.

Confidence Decay:
- Probed within 1 hour: confidence = 1.0
- Probed within 24 hours: confidence = 0.8
- Probed within 7 days: confidence = 0.5
- Older than 7 days: confidence = 0.2
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

from .models import WEIGHTS, ProbeResult, SecurityScan, TrustScore, Window

# Time thresholds in seconds
ONE_HOUR = 3600
TWENTY_FOUR_HOURS = 86400
SEVEN_DAYS = 604800

# Window durations in seconds
WINDOW_SECONDS = {
    Window.H24: TWENTY_FOUR_HOURS,
    Window.D7: SEVEN_DAYS,
    Window.D30: 30 * 86400,
}


def compute_confidence(last_probed_at: float | None, now: float | None = None) -> float:
    """Compute confidence score based on data freshness.

    Args:
        last_probed_at: Unix timestamp of most recent probe. None = no data.
        now: Current time (defaults to time.time()).

    Returns:
        Confidence value between 0.0 and 1.0.
    """
    if last_probed_at is None:
        return 0.0

    if now is None:
        now = time.time()

    age = now - last_probed_at
    if age <= ONE_HOUR:
        return 1.0
    if age <= TWENTY_FOUR_HOURS:
        return 0.8
    if age <= SEVEN_DAYS:
        return 0.5
    return 0.2


def compute_reliability(probes: list[ProbeResult]) -> float:
    """Compute reliability score (0-100) from probe results.

    Factors:
    - Uptime %: proportion of probes with status 200
    - Error rate: proportion of probes with errors
    - Timeout rate: proportion of probes exceeding 5000ms
    """
    if not probes:
        return 0.0

    total = len(probes)
    successful = sum(1 for p in probes if p.status_code == 200)
    errors = sum(1 for p in probes if p.error is not None)
    timeouts = sum(1 for p in probes if p.latency_ms > 5000)

    uptime_pct = successful / total
    error_rate = errors / total
    timeout_rate = timeouts / total

    # Weighted: 50% uptime, 30% error-free, 20% no-timeout
    score = (uptime_pct * 50.0) + ((1.0 - error_rate) * 30.0) + ((1.0 - timeout_rate) * 20.0)
    return max(0.0, min(100.0, score))


def compute_security(scans: list[SecurityScan]) -> float:
    """Compute security score (0-100) from security scan results.

    Uses the most recent scan. Factors:
    - TLS enabled: 30 points
    - Auth required: 25 points
    - Input validation score: scaled to 25 points
    - CVE count: 20 points base, penalized per CVE
    """
    if not scans:
        return 0.0

    # Use most recent scan
    scan = max(scans, key=lambda s: s.timestamp)

    tls_points = 30.0 if scan.tls_enabled else 0.0
    auth_points = 25.0 if scan.auth_required else 0.0
    validation_points = (scan.input_validation_score / 100.0) * 25.0
    # Each CVE deducts 5 points from the 20-point base, minimum 0
    cve_points = max(0.0, 20.0 - (scan.cve_count * 5.0))

    return max(0.0, min(100.0, tls_points + auth_points + validation_points + cve_points))


def compute_documentation(probes: list[ProbeResult]) -> float:
    """Compute documentation score (0-100) from probe results.

    Factors:
    - Tool count > 0: base 30 points
    - Documentation ratio: tools_documented / tools_count, scaled to 70 points
    """
    if not probes:
        return 0.0

    # Use the most recent probe with tool data
    probes_with_tools = [p for p in probes if p.tools_count > 0]
    if not probes_with_tools:
        return 0.0

    latest = max(probes_with_tools, key=lambda p: p.timestamp)

    has_tools = 30.0  # Base for having any tools
    if latest.tools_count > 0:
        doc_ratio = latest.tools_documented / latest.tools_count
    else:
        doc_ratio = 0.0

    doc_points = doc_ratio * 70.0

    return max(0.0, min(100.0, has_tools + doc_points))


def compute_responsiveness(probes: list[ProbeResult]) -> float:
    """Compute responsiveness score (0-100) from probe results.

    Factors:
    - Latency p50: target < 200ms for full score
    - Latency p95: target < 1000ms for full score
    - Consistency: low stddev = high score
    """
    if not probes:
        return 0.0

    latencies = [p.latency_ms for p in probes if p.status_code == 200]
    if not latencies:
        return 0.0

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    # P50
    p50_idx = int(n * 0.5)
    p50 = latencies_sorted[min(p50_idx, n - 1)]
    # P95
    p95_idx = int(n * 0.95)
    p95 = latencies_sorted[min(p95_idx, n - 1)]

    # Score p50: 200ms = 40pts, scales linearly to 0 at 2000ms
    p50_score = max(0.0, 40.0 * (1.0 - p50 / 2000.0))

    # Score p95: 1000ms = 30pts, scales linearly to 0 at 5000ms
    p95_score = max(0.0, 30.0 * (1.0 - p95 / 5000.0))

    # Consistency: stddev. Target < 100ms for 30pts
    if n >= 2:
        stddev = statistics.stdev(latencies)
        consistency_score = max(0.0, 30.0 * (1.0 - stddev / 1000.0))
    else:
        # Single probe — can't measure consistency, give moderate score
        consistency_score = 15.0

    return max(0.0, min(100.0, p50_score + p95_score + consistency_score))


def compute_composite(
    reliability: float,
    security: float,
    documentation: float,
    responsiveness: float,
) -> float:
    """Compute weighted composite trust score.

    Weights: reliability 0.35, security 0.30, documentation 0.20, responsiveness 0.15.
    """
    composite = (
        reliability * WEIGHTS["reliability"]
        + security * WEIGHTS["security"]
        + documentation * WEIGHTS["documentation"]
        + responsiveness * WEIGHTS["responsiveness"]
    )
    return max(0.0, min(100.0, composite))


def compute_trust_score(
    server_id: str,
    probes: list[ProbeResult],
    scans: list[SecurityScan],
    window: Window = Window.H24,
    now: float | None = None,
) -> TrustScore:
    """Compute a complete trust score from raw probe and scan data.

    This is the main entry point. Pure function — no I/O.

    Args:
        server_id: The server being scored.
        probes: Probe results within the relevant time window.
        scans: Security scans (uses most recent).
        window: Time window for aggregation.
        now: Current time (defaults to time.time()).

    Returns:
        A complete TrustScore with dimensional breakdown.
    """
    if now is None:
        now = time.time()

    # Filter probes to the window
    window_start = now - WINDOW_SECONDS[window]
    windowed_probes = [p for p in probes if p.timestamp >= window_start]

    reliability = compute_reliability(windowed_probes)
    security = compute_security(scans)
    documentation = compute_documentation(windowed_probes)
    responsiveness = compute_responsiveness(windowed_probes)
    composite = compute_composite(reliability, security, documentation, responsiveness)

    # Confidence based on most recent probe timestamp
    last_probed = max((p.timestamp for p in probes), default=None) if probes else None
    confidence = compute_confidence(last_probed, now)

    return TrustScore(
        server_id=server_id,
        timestamp=now,
        window=window,
        reliability_score=round(reliability, 2),
        security_score=round(security, 2),
        documentation_score=round(documentation, 2),
        responsiveness_score=round(responsiveness, 2),
        composite_score=round(composite, 2),
        confidence=confidence,
    )


@dataclass
class ScoreEngine:
    """Score computation engine that reads from storage and writes results.

    Wraps the pure computation functions with I/O.
    """

    storage: StorageBackend  # noqa: F821 — forward reference

    async def compute_and_store(
        self,
        server_id: str,
        window: Window = Window.H24,
        now: float | None = None,
    ) -> TrustScore:
        """Compute trust score from stored data and persist the result."""
        if now is None:
            now = time.time()

        # Fetch all relevant data
        window_seconds = WINDOW_SECONDS[window]
        since = now - window_seconds

        probes = await self.storage.get_probe_results(server_id, since=since)
        scans = await self.storage.get_security_scans(server_id)

        score = compute_trust_score(server_id, probes, scans, window, now)
        await self.storage.store_trust_score(score)

        return score
