"""Pydantic models for the Reputation Data Collection Pipeline.

All timestamps are Unix floats (time.time()).
Intervals are in seconds.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProbeErrorType(str, Enum):
    """Classification of probe error types."""
    SUCCESS = "success"
    TIMEOUT = "timeout"
    CONNECTION_REFUSED = "connection_refused"
    DNS_ERROR = "dns_error"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    SSL_ERROR = "ssl_error"
    UNKNOWN = "unknown"


class ProbeTarget(BaseModel):
    """A server registered for continuous monitoring."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "server_id": "srv-west-01",
                    "url": "https://api.example.com/health",
                    "probe_interval": 300.0,
                    "scan_interval": 3600.0,
                    "last_probed": 1711612800.0,
                    "last_scanned": 1711609200.0,
                    "active": True,
                }
            ]
        },
    )

    server_id: str
    url: str
    probe_interval: float = Field(default=300.0, gt=0, description="Probe interval in seconds")
    scan_interval: float = Field(default=3600.0, gt=0, description="Scan interval in seconds")
    last_probed: float | None = None
    last_scanned: float | None = None
    active: bool = True


class ProbeSchedule(BaseModel):
    """Schedule configuration for health probes."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "interval_seconds": 300.0,
                    "timeout_seconds": 10.0,
                    "max_retries": 2,
                }
            ]
        },
    )

    interval_seconds: float = Field(default=300.0, gt=0, description="Seconds between probes")
    timeout_seconds: float = Field(default=10.0, gt=0, description="HTTP request timeout")
    max_retries: int = Field(default=0, ge=0, description="Number of retries on failure")


class ScanSchedule(BaseModel):
    """Schedule configuration for security scans."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "interval_seconds": 3600.0,
                    "timeout_seconds": 30.0,
                }
            ]
        },
    )

    interval_seconds: float = Field(default=3600.0, gt=0, description="Seconds between scans")
    timeout_seconds: float = Field(default=30.0, gt=0, description="Scan timeout")


class PipelineConfig(BaseModel):
    """Configuration for the reputation pipeline."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "probe_schedule": {
                        "interval_seconds": 300.0,
                        "timeout_seconds": 10.0,
                        "max_retries": 2,
                    },
                    "scan_schedule": {
                        "interval_seconds": 3600.0,
                        "timeout_seconds": 30.0,
                    },
                    "cycle_interval": 60.0,
                    "db_path": "reputation.db",
                }
            ]
        },
    )

    probe_schedule: ProbeSchedule = Field(default_factory=ProbeSchedule)
    scan_schedule: ScanSchedule = Field(default_factory=ScanSchedule)
    cycle_interval: float = Field(default=60.0, gt=0, description="Seconds between pipeline cycles")
    db_path: str = Field(default="reputation.db", description="SQLite database path")


class SecurityHeaders(BaseModel):
    """Results of security header analysis."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "has_hsts": True,
                    "has_csp": True,
                    "has_x_frame_options": True,
                    "has_x_content_type_options": True,
                    "has_referrer_policy": False,
                    "header_score": 80.0,
                }
            ]
        }
    )

    has_hsts: bool = False
    has_csp: bool = False
    has_x_frame_options: bool = False
    has_x_content_type_options: bool = False
    has_referrer_policy: bool = False
    header_score: float = Field(default=0.0, ge=0.0, le=100.0)


class TLSInfo(BaseModel):
    """TLS certificate information."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "enabled": True,
                    "valid": True,
                    "days_until_expiry": 245,
                    "protocol_version": "TLSv1.3",
                }
            ]
        }
    )

    enabled: bool = False
    valid: bool = False
    days_until_expiry: int | None = None
    protocol_version: str | None = None


class ScanResult(BaseModel):
    """Complete result of a security scan."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "server_id": "srv-west-01",
                    "timestamp": 1711612800.0,
                    "tls_info": {
                        "enabled": True,
                        "valid": True,
                        "days_until_expiry": 245,
                        "protocol_version": "TLSv1.3",
                    },
                    "security_headers": {
                        "has_hsts": True,
                        "has_csp": True,
                        "has_x_frame_options": True,
                        "has_x_content_type_options": True,
                        "has_referrer_policy": False,
                        "header_score": 80.0,
                    },
                    "auth_required": True,
                    "input_validation_score": 95.0,
                }
            ]
        }
    )

    server_id: str
    timestamp: float
    tls_info: TLSInfo = Field(default_factory=TLSInfo)
    security_headers: SecurityHeaders = Field(default_factory=SecurityHeaders)
    auth_required: bool = False
    input_validation_score: float = Field(default=0.0, ge=0.0, le=100.0)
