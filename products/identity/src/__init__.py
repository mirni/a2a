"""a2a-identity: Agent identity, attestation, and reputation.

Provides cryptographic identity, metric attestation, verified claims,
and reputation scoring for agents.
"""

from .api import IdentityAPI
from .models import AgentIdentity, MetricSubmissionResult, VerifiedClaim
from .storage import IdentityStorage

__all__ = [
    "AgentIdentity",
    "IdentityAPI",
    "IdentityStorage",
    "MetricSubmissionResult",
    "VerifiedClaim",
]

__version__ = "0.2.0"
