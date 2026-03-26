"""a2a_trust: Agent Trust & Reputation Scoring Engine.

Evaluates MCP servers on reliability, security, documentation,
and responsiveness to produce composite trust scores.
"""

from .api import ServerNotFoundError, TrustAPI
from .models import (
    WEIGHTS,
    ProbeResult,
    SecurityScan,
    Server,
    TransportType,
    TrustScore,
    Window,
)
from .prober import Prober
from .scanner import Scanner
from .scorer import ScoreEngine, compute_trust_score
from .storage import StorageBackend

__all__ = [
    "WEIGHTS",
    "Prober",
    "ProbeResult",
    "Scanner",
    "ScoreEngine",
    "SecurityScan",
    "Server",
    "ServerNotFoundError",
    "StorageBackend",
    "TransportType",
    "TrustAPI",
    "TrustScore",
    "Window",
    "compute_trust_score",
]

__version__ = "0.1.0"
