"""a2a-identity: Agent identity, attestation, and reputation.

Provides cryptographic identity, metric attestation, verified claims,
and reputation scoring for agents.
"""

from .api import IdentityAPI
from .models import AgentIdentity, MetricSubmissionResult, Organization, OrgMembership, VerifiedClaim
from .org_api import (
    AlreadyMemberError,
    MemberNotFoundError,
    NotAuthorizedError,
    OrgAPI,
    OrgNotFoundError,
)
from .storage import IdentityStorage

__all__ = [
    "AgentIdentity",
    "AlreadyMemberError",
    "IdentityAPI",
    "IdentityStorage",
    "MemberNotFoundError",
    "MetricSubmissionResult",
    "NotAuthorizedError",
    "OrgAPI",
    "OrgMembership",
    "OrgNotFoundError",
    "Organization",
    "VerifiedClaim",
]

__version__ = "0.2.0"
