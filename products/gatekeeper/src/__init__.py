"""a2a-gatekeeper: Formal verification and proof management.

Provides Z3 SMT-based verification of workflow safety properties,
cryptographic proof generation, and proof verification for agents.
"""

from .api import (
    GatekeeperAPI,
    IdempotencyConflictError,
    JobAlreadyTerminalError,
    JobNotFoundError,
    ProofNotFoundError,
)
from .models import (
    ProofArtifact,
    PropertySpec,
    VerificationJob,
    VerificationResult,
    VerificationScope,
    VerificationStatus,
)
from .storage import GatekeeperStorage

__all__ = [
    "GatekeeperAPI",
    "GatekeeperStorage",
    "IdempotencyConflictError",
    "JobAlreadyTerminalError",
    "JobNotFoundError",
    "ProofArtifact",
    "ProofNotFoundError",
    "PropertySpec",
    "VerificationJob",
    "VerificationResult",
    "VerificationScope",
    "VerificationStatus",
]

__version__ = "0.1.0"
