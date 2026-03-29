"""Tests for score computation engine.

All score functions are pure — no I/O needed. Tests use known inputs
and verify deterministic outputs.
"""

from __future__ import annotations

import time

from src.models import ProbeResult, SecurityScan, Window
from src.scorer import (
    ONE_HOUR,
    SEVEN_DAYS,
    TWENTY_FOUR_HOURS,
    ScoreEngine,
    compute_composite,
    compute_confidence,
    compute_documentation,
    compute_reliability,
    compute_responsiveness,
    compute_security,
    compute_trust_score,
)


class TestConfidenceDecay:
    def test_probed_within_1_hour(self):
        now = time.time()
        assert compute_confidence(now - 1800, now) == 1.0  # 30 min ago

    def test_probed_exactly_1_hour(self):
        now = time.time()
        assert compute_confidence(now - ONE_HOUR, now) == 1.0

    def test_probed_within_24_hours(self):
        now = time.time()
        assert compute_confidence(now - 7200, now) == 0.8  # 2 hours ago

    def test_probed_exactly_24_hours(self):
        now = time.time()
        assert compute_confidence(now - TWENTY_FOUR_HOURS, now) == 0.8

    def test_probed_within_7_days(self):
        now = time.time()
        assert compute_confidence(now - 172800, now) == 0.5  # 2 days ago

    def test_probed_exactly_7_days(self):
        now = time.time()
        assert compute_confidence(now - SEVEN_DAYS, now) == 0.5

    def test_probed_older_than_7_days(self):
        now = time.time()
        assert compute_confidence(now - (8 * 86400), now) == 0.2

    def test_never_probed(self):
        assert compute_confidence(None) == 0.0

    def test_just_probed(self):
        now = time.time()
        assert compute_confidence(now, now) == 1.0


class TestReliability:
    def test_empty_probes(self):
        assert compute_reliability([]) == 0.0

    def test_all_successful(self):
        probes = [ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=200) for _ in range(10)]
        score = compute_reliability(probes)
        # 100% uptime (50) + 0% errors (30) + 0% timeouts (20) = 100
        assert score == 100.0

    def test_all_errors(self):
        probes = [
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=500, error="fail")
            for _ in range(10)
        ]
        score = compute_reliability(probes)
        # 0% uptime (0) + 100% errors (0) + 0% timeouts (20) = 20
        assert score == 20.0

    def test_mixed_results(self):
        probes = [
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=200),
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=200),
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=6000, status_code=500, error="timeout"),
        ]
        score = compute_reliability(probes)
        # Uptime: 2/3 * 50 = 33.33
        # Error-free: 2/3 * 30 = 20
        # No-timeout: 2/3 * 20 = 13.33
        expected = (2 / 3 * 50) + (2 / 3 * 30) + (2 / 3 * 20)
        assert abs(score - expected) < 0.01

    def test_timeout_probes(self):
        probes = [
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=6000, status_code=200),
        ]
        score = compute_reliability(probes)
        # Uptime 100% (50) + error-free 100% (30) + timeout 100% (0) = 80
        assert score == 80.0


class TestSecurity:
    def test_empty_scans(self):
        assert compute_security([]) == 0.0

    def test_perfect_security(self):
        scans = [
            SecurityScan(
                server_id="s",
                timestamp=time.time(),
                tls_enabled=True,
                auth_required=True,
                input_validation_score=100.0,
                cve_count=0,
            )
        ]
        # TLS (30) + Auth (25) + Validation (25) + CVE base (20) = 100
        assert compute_security(scans) == 100.0

    def test_no_security(self):
        scans = [
            SecurityScan(
                server_id="s",
                timestamp=time.time(),
                tls_enabled=False,
                auth_required=False,
                input_validation_score=0.0,
                cve_count=10,
            )
        ]
        # TLS (0) + Auth (0) + Validation (0) + CVE (max(0, 20 - 50) = 0)
        assert compute_security(scans) == 0.0

    def test_partial_security(self):
        scans = [
            SecurityScan(
                server_id="s",
                timestamp=time.time(),
                tls_enabled=True,
                auth_required=False,
                input_validation_score=50.0,
                cve_count=2,
            )
        ]
        # TLS (30) + Auth (0) + Validation (50/100 * 25 = 12.5) + CVE (20 - 10 = 10)
        expected = 30.0 + 0.0 + 12.5 + 10.0
        assert compute_security(scans) == expected

    def test_uses_most_recent_scan(self):
        now = time.time()
        scans = [
            SecurityScan(
                server_id="s",
                timestamp=now - 100,
                tls_enabled=False,
                auth_required=False,
            ),
            SecurityScan(
                server_id="s",
                timestamp=now,
                tls_enabled=True,
                auth_required=True,
                input_validation_score=100.0,
                cve_count=0,
            ),
        ]
        assert compute_security(scans) == 100.0


class TestDocumentation:
    def test_empty_probes(self):
        assert compute_documentation([]) == 0.0

    def test_no_tools(self):
        probes = [
            ProbeResult(
                server_id="s", timestamp=time.time(), latency_ms=100, status_code=200, tools_count=0, tools_documented=0
            )
        ]
        assert compute_documentation(probes) == 0.0

    def test_all_documented(self):
        probes = [
            ProbeResult(
                server_id="s",
                timestamp=time.time(),
                latency_ms=100,
                status_code=200,
                tools_count=10,
                tools_documented=10,
            )
        ]
        # Has tools (30) + 100% doc ratio (70) = 100
        assert compute_documentation(probes) == 100.0

    def test_partial_documentation(self):
        probes = [
            ProbeResult(
                server_id="s",
                timestamp=time.time(),
                latency_ms=100,
                status_code=200,
                tools_count=10,
                tools_documented=5,
            )
        ]
        # Has tools (30) + 50% doc ratio (35) = 65
        assert compute_documentation(probes) == 65.0

    def test_uses_most_recent_with_tools(self):
        now = time.time()
        probes = [
            ProbeResult(
                server_id="s", timestamp=now - 100, latency_ms=100, status_code=200, tools_count=10, tools_documented=2
            ),
            ProbeResult(
                server_id="s", timestamp=now, latency_ms=100, status_code=200, tools_count=10, tools_documented=8
            ),
        ]
        # Uses newest: 30 + (8/10) * 70 = 30 + 56 = 86
        assert compute_documentation(probes) == 86.0


class TestResponsiveness:
    def test_empty_probes(self):
        assert compute_responsiveness([]) == 0.0

    def test_no_successful_probes(self):
        probes = [ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=500, error="fail")]
        assert compute_responsiveness(probes) == 0.0

    def test_fast_consistent_server(self):
        probes = [ProbeResult(server_id="s", timestamp=time.time(), latency_ms=50, status_code=200) for _ in range(10)]
        score = compute_responsiveness(probes)
        # p50=50ms: 40*(1-50/2000) = 39.0
        # p95=50ms: 30*(1-50/5000) = 29.7
        # stddev=0: 30*(1-0/1000) = 30.0
        # Total: 98.7
        assert score > 95.0

    def test_slow_server(self):
        probes = [
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=4000, status_code=200) for _ in range(10)
        ]
        score = compute_responsiveness(probes)
        # p50=4000ms: 40*(1-4000/2000) = 40*(-1) = 0 (clamped)
        # p95=4000ms: 30*(1-4000/5000) = 30*0.2 = 6.0
        # stddev=0: 30
        # Total: 36
        assert 30.0 <= score <= 40.0

    def test_single_probe_moderate_consistency(self):
        probes = [ProbeResult(server_id="s", timestamp=time.time(), latency_ms=100, status_code=200)]
        score = compute_responsiveness(probes)
        # p50=100: 40*(1-100/2000) = 38.0
        # p95=100: 30*(1-100/5000) = 29.4
        # consistency: 15 (single probe)
        assert 80.0 <= score <= 85.0

    def test_inconsistent_server(self):
        probes = [
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=50, status_code=200),
            ProbeResult(server_id="s", timestamp=time.time(), latency_ms=3000, status_code=200),
        ]
        score = compute_responsiveness(probes)
        # High stddev should reduce consistency score
        assert score < 80.0


class TestComposite:
    def test_perfect_scores(self):
        c = compute_composite(100, 100, 100, 100)
        assert c == 100.0

    def test_zero_scores(self):
        c = compute_composite(0, 0, 0, 0)
        assert c == 0.0

    def test_weights_applied(self):
        # Only reliability at 100, rest 0
        c = compute_composite(100, 0, 0, 0)
        assert c == 35.0

        # Only security at 100
        c = compute_composite(0, 100, 0, 0)
        assert c == 30.0

        # Only documentation at 100
        c = compute_composite(0, 0, 100, 0)
        assert c == 20.0

        # Only responsiveness at 100
        c = compute_composite(0, 0, 0, 100)
        assert c == 15.0


class TestComputeTrustScore:
    def test_full_computation(self):
        now = time.time()
        probes = [
            ProbeResult(
                server_id="s",
                timestamp=now - 60,
                latency_ms=100,
                status_code=200,
                tools_count=5,
                tools_documented=5,
            ),
            ProbeResult(
                server_id="s",
                timestamp=now - 30,
                latency_ms=120,
                status_code=200,
                tools_count=5,
                tools_documented=5,
            ),
        ]
        scans = [
            SecurityScan(
                server_id="s",
                timestamp=now,
                tls_enabled=True,
                auth_required=True,
                input_validation_score=100.0,
                cve_count=0,
            ),
        ]

        score = compute_trust_score("s", probes, scans, Window.H24, now)

        assert score.server_id == "s"
        assert score.window == Window.H24
        assert score.reliability_score > 0
        assert score.security_score == 100.0
        assert score.documentation_score == 100.0
        assert score.responsiveness_score > 0
        assert score.composite_score > 0
        assert score.confidence == 1.0

    def test_no_data(self):
        now = time.time()
        score = compute_trust_score("s", [], [], Window.H24, now)
        assert score.composite_score == 0.0
        assert score.confidence == 0.0

    def test_window_filtering(self):
        """Probes outside the window should be excluded from scoring."""
        now = time.time()
        old_probe = ProbeResult(
            server_id="s",
            timestamp=now - 100000,  # ~27 hours ago
            latency_ms=100,
            status_code=200,
            tools_count=10,
            tools_documented=10,
        )
        recent_probe = ProbeResult(
            server_id="s",
            timestamp=now - 3600,  # 1 hour ago
            latency_ms=5000,
            status_code=500,
            error="fail",
        )

        # 24h window: only recent_probe included
        score = compute_trust_score("s", [old_probe, recent_probe], [], Window.H24, now)
        # Recent probe is an error with no tools — should score poorly
        assert score.reliability_score < 50
        assert score.documentation_score == 0.0

    def test_stale_data_confidence_decay(self):
        """Old probes should reduce confidence."""
        now = time.time()
        old_probe = ProbeResult(
            server_id="s",
            timestamp=now - 200000,  # ~2.3 days ago
            latency_ms=100,
            status_code=200,
        )
        score = compute_trust_score("s", [old_probe], [], Window.D7, now)
        assert score.confidence == 0.5  # Within 7 days


class TestScoreEngine:
    async def test_compute_and_store(self, storage, sample_server):
        """ScoreEngine should compute from stored data and persist."""
        now = time.time()
        # Insert some probe data
        await storage.store_probe_result(
            ProbeResult(
                server_id=sample_server.id,
                timestamp=now - 60,
                latency_ms=100,
                status_code=200,
                tools_count=3,
                tools_documented=3,
            )
        )
        await storage.store_security_scan(
            SecurityScan(
                server_id=sample_server.id,
                timestamp=now,
                tls_enabled=True,
                auth_required=True,
                input_validation_score=80.0,
                cve_count=0,
            )
        )

        engine = ScoreEngine(storage=storage)
        score = await engine.compute_and_store(sample_server.id, Window.H24, now)

        assert score.server_id == sample_server.id
        assert score.composite_score > 0

        # Verify it was persisted
        stored = await storage.get_latest_trust_score(sample_server.id, Window.H24)
        assert stored is not None
        assert stored.composite_score == score.composite_score
