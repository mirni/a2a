"""Tests for reputation pipeline models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from products.reputation.src.models import (
    PipelineConfig,
    ProbeErrorType,
    ProbeSchedule,
    ProbeTarget,
    ScanResult,
    ScanSchedule,
    SecurityHeaders,
    TLSInfo,
)


class TestProbeTarget:
    def test_create_default(self):
        t = ProbeTarget(server_id="svc-1", url="https://example.com")
        assert t.server_id == "svc-1"
        assert t.url == "https://example.com"
        assert t.probe_interval == 300.0
        assert t.scan_interval == 3600.0
        assert t.last_probed is None
        assert t.last_scanned is None
        assert t.active is True

    def test_create_custom_intervals(self):
        t = ProbeTarget(
            server_id="svc-2",
            url="http://localhost:8080",
            probe_interval=60.0,
            scan_interval=600.0,
        )
        assert t.probe_interval == 60.0
        assert t.scan_interval == 600.0

    def test_create_with_timestamps(self):
        t = ProbeTarget(
            server_id="svc-3",
            url="https://example.com",
            last_probed=1000.0,
            last_scanned=900.0,
        )
        assert t.last_probed == 1000.0
        assert t.last_scanned == 900.0

    def test_inactive_target(self):
        t = ProbeTarget(server_id="svc-4", url="https://example.com", active=False)
        assert t.active is False

    def test_invalid_probe_interval(self):
        with pytest.raises(ValidationError):
            ProbeTarget(server_id="svc", url="https://example.com", probe_interval=0)

    def test_invalid_scan_interval(self):
        with pytest.raises(ValidationError):
            ProbeTarget(server_id="svc", url="https://example.com", scan_interval=-1)

    def test_serialization_roundtrip(self):
        t = ProbeTarget(server_id="svc-5", url="https://example.com", last_probed=100.0)
        data = t.model_dump()
        t2 = ProbeTarget(**data)
        assert t == t2


class TestProbeSchedule:
    def test_defaults(self):
        s = ProbeSchedule()
        assert s.interval_seconds == 300.0
        assert s.timeout_seconds == 10.0
        assert s.max_retries == 0

    def test_custom_values(self):
        s = ProbeSchedule(interval_seconds=60.0, timeout_seconds=5.0, max_retries=3)
        assert s.interval_seconds == 60.0
        assert s.timeout_seconds == 5.0
        assert s.max_retries == 3

    def test_invalid_interval(self):
        with pytest.raises(ValidationError):
            ProbeSchedule(interval_seconds=0)

    def test_invalid_timeout(self):
        with pytest.raises(ValidationError):
            ProbeSchedule(timeout_seconds=-1)

    def test_invalid_retries(self):
        with pytest.raises(ValidationError):
            ProbeSchedule(max_retries=-1)


class TestScanSchedule:
    def test_defaults(self):
        s = ScanSchedule()
        assert s.interval_seconds == 3600.0
        assert s.timeout_seconds == 30.0

    def test_custom_values(self):
        s = ScanSchedule(interval_seconds=600.0, timeout_seconds=15.0)
        assert s.interval_seconds == 600.0
        assert s.timeout_seconds == 15.0

    def test_invalid_interval(self):
        with pytest.raises(ValidationError):
            ScanSchedule(interval_seconds=0)


class TestPipelineConfig:
    def test_defaults(self):
        c = PipelineConfig()
        assert c.probe_schedule.interval_seconds == 300.0
        assert c.scan_schedule.interval_seconds == 3600.0
        assert c.cycle_interval == 60.0
        assert c.db_path == "reputation.db"

    def test_custom_config(self):
        c = PipelineConfig(
            probe_schedule=ProbeSchedule(interval_seconds=30.0),
            scan_schedule=ScanSchedule(interval_seconds=120.0),
            cycle_interval=10.0,
            db_path="/tmp/test.db",
        )
        assert c.probe_schedule.interval_seconds == 30.0
        assert c.scan_schedule.interval_seconds == 120.0
        assert c.cycle_interval == 10.0
        assert c.db_path == "/tmp/test.db"

    def test_invalid_cycle_interval(self):
        with pytest.raises(ValidationError):
            PipelineConfig(cycle_interval=0)


class TestProbeErrorType:
    def test_all_values(self):
        assert ProbeErrorType.SUCCESS == "success"
        assert ProbeErrorType.TIMEOUT == "timeout"
        assert ProbeErrorType.CONNECTION_REFUSED == "connection_refused"
        assert ProbeErrorType.DNS_ERROR == "dns_error"
        assert ProbeErrorType.HTTP_4XX == "http_4xx"
        assert ProbeErrorType.HTTP_5XX == "http_5xx"
        assert ProbeErrorType.SSL_ERROR == "ssl_error"
        assert ProbeErrorType.UNKNOWN == "unknown"

    def test_enum_count(self):
        assert len(ProbeErrorType) == 8


class TestSecurityHeaders:
    def test_defaults(self):
        h = SecurityHeaders()
        assert h.has_hsts is False
        assert h.has_csp is False
        assert h.has_x_frame_options is False
        assert h.has_x_content_type_options is False
        assert h.has_referrer_policy is False
        assert h.header_score == 0.0

    def test_all_present(self):
        h = SecurityHeaders(
            has_hsts=True,
            has_csp=True,
            has_x_frame_options=True,
            has_x_content_type_options=True,
            has_referrer_policy=True,
            header_score=100.0,
        )
        assert h.header_score == 100.0

    def test_partial(self):
        h = SecurityHeaders(has_hsts=True, has_csp=True, header_score=40.0)
        assert h.has_hsts is True
        assert h.has_csp is True
        assert h.has_x_frame_options is False

    def test_invalid_score(self):
        with pytest.raises(ValidationError):
            SecurityHeaders(header_score=101.0)


class TestTLSInfo:
    def test_defaults(self):
        t = TLSInfo()
        assert t.enabled is False
        assert t.valid is False
        assert t.days_until_expiry is None
        assert t.protocol_version is None

    def test_valid_tls(self):
        t = TLSInfo(enabled=True, valid=True, protocol_version="TLSv1.3", days_until_expiry=90)
        assert t.enabled is True
        assert t.valid is True
        assert t.protocol_version == "TLSv1.3"
        assert t.days_until_expiry == 90

    def test_invalid_tls(self):
        t = TLSInfo(enabled=True, valid=False)
        assert t.enabled is True
        assert t.valid is False


class TestScanResult:
    def test_create(self):
        r = ScanResult(server_id="svc-1", timestamp=1000.0)
        assert r.server_id == "svc-1"
        assert r.timestamp == 1000.0
        assert r.tls_info.enabled is False
        assert r.auth_required is False

    def test_full_scan_result(self):
        r = ScanResult(
            server_id="svc-1",
            timestamp=1000.0,
            tls_info=TLSInfo(enabled=True, valid=True),
            security_headers=SecurityHeaders(has_hsts=True, header_score=20.0),
            auth_required=True,
            input_validation_score=75.0,
        )
        assert r.tls_info.enabled is True
        assert r.security_headers.has_hsts is True
        assert r.auth_required is True
        assert r.input_validation_score == 75.0

    def test_invalid_validation_score(self):
        with pytest.raises(ValidationError):
            ScanResult(server_id="svc-1", timestamp=1000.0, input_validation_score=101.0)
