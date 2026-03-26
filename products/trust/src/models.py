"""Pydantic models for the Trust & Reputation engine.

All timestamps are Unix floats (time.time()).
Scores are 0-100. Confidence is 0.0-1.0.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class TransportType(str, Enum):
    """MCP server transport type."""
    STDIO = "stdio"
    HTTP = "http"


class Server(BaseModel):
    """A registered MCP server."""
    id: str
    name: str
    url: str
    transport_type: TransportType = TransportType.HTTP
    registered_at: float
    last_probed_at: float | None = None


class ProbeResult(BaseModel):
    """Result of a single health probe against an MCP server."""
    server_id: str
    timestamp: float
    latency_ms: float
    status_code: int
    error: str | None = None
    tools_count: int = 0
    tools_documented: int = 0


class SecurityScan(BaseModel):
    """Result of a security scan against an MCP server."""
    server_id: str
    timestamp: float
    tls_enabled: bool = False
    auth_required: bool = False
    input_validation_score: float = Field(default=0.0, ge=0.0, le=100.0)
    cve_count: int = 0


class Window(str, Enum):
    """Time window for score aggregation."""
    H24 = "24h"
    D7 = "7d"
    D30 = "30d"


class TrustScore(BaseModel):
    """Computed trust score for a server over a time window."""
    server_id: str
    timestamp: float
    window: Window = Window.H24
    reliability_score: float = Field(default=0.0, ge=0.0, le=100.0)
    security_score: float = Field(default=0.0, ge=0.0, le=100.0)
    documentation_score: float = Field(default=0.0, ge=0.0, le=100.0)
    responsiveness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    composite_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# Weight constants for composite score calculation
WEIGHTS = {
    "reliability": 0.35,
    "security": 0.30,
    "documentation": 0.20,
    "responsiveness": 0.15,
}
