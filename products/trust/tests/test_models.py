"""Tests for Pydantic models."""

from __future__ import annotations

import time

from src.models import (
    WEIGHTS,
    ProbeResult,
    SecurityScan,
    Server,
    TransportType,
    TrustScore,
    Window,
)


class TestServer:
    def test_create_server(self):
        s = Server(
            id="srv-1",
            name="My Server",
            url="https://example.com",
            transport_type=TransportType.HTTP,
            registered_at=time.time(),
        )
        assert s.id == "srv-1"
        assert s.transport_type == TransportType.HTTP
        assert s.last_probed_at is None

    def test_server_stdio_transport(self):
        s = Server(
            id="srv-2",
            name="Stdio Server",
            url="stdio://local",
            transport_type=TransportType.STDIO,
            registered_at=time.time(),
        )
        assert s.transport_type == TransportType.STDIO


class TestProbeResult:
    def test_create_probe_success(self):
        p = ProbeResult(
            server_id="srv-1",
            timestamp=time.time(),
            latency_ms=150.0,
            status_code=200,
            tools_count=5,
            tools_documented=3,
        )
        assert p.error is None
        assert p.tools_count == 5

    def test_create_probe_error(self):
        p = ProbeResult(
            server_id="srv-1",
            timestamp=time.time(),
            latency_ms=5000.0,
            status_code=500,
            error="Connection timeout",
        )
        assert p.error == "Connection timeout"


class TestSecurityScan:
    def test_create_scan(self):
        s = SecurityScan(
            server_id="srv-1",
            timestamp=time.time(),
            tls_enabled=True,
            auth_required=True,
            input_validation_score=85.0,
            cve_count=0,
        )
        assert s.tls_enabled is True
        assert s.input_validation_score == 85.0

    def test_validation_score_bounds(self):
        """input_validation_score must be 0-100."""
        import pytest

        with pytest.raises(Exception):
            SecurityScan(
                server_id="srv-1",
                timestamp=time.time(),
                input_validation_score=150.0,
            )


class TestTrustScore:
    def test_create_score(self):
        ts = TrustScore(
            server_id="srv-1",
            timestamp=time.time(),
            window=Window.H24,
            reliability_score=80.0,
            security_score=70.0,
            documentation_score=90.0,
            responsiveness_score=85.0,
            composite_score=80.0,
            confidence=1.0,
        )
        assert ts.composite_score == 80.0
        assert ts.window == Window.H24

    def test_window_values(self):
        assert Window.H24.value == "24h"
        assert Window.D7.value == "7d"
        assert Window.D30.value == "30d"


class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_weight_keys(self):
        assert set(WEIGHTS.keys()) == {"reliability", "security", "documentation", "responsiveness"}
