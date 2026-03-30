"""Pydantic models for the Agent Identity system.

Covers cryptographic identity (Ed25519 key pairs), metric commitments
(HMAC-based hiding commitments), auditor attestations, verified claims,
and consumer-side reputation.

All timestamps are Unix floats (time.time()).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentIdentity(BaseModel):
    """Cryptographic identity for an agent (Ed25519 key pair)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-7f3a2b",
                    "public_key": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa3f4a18446b7e8c3042b58",
                    "created_at": 1711612800.0,
                    "org_id": "acme-capital",
                }
            ]
        }
    )

    agent_id: str
    public_key: str  # Ed25519 public key hex
    created_at: float
    org_id: str = "default"


class MetricCommitment(BaseModel):
    """A hiding commitment to a numeric metric value.

    commitment_hash = SHA3-256(value_scaled_bytes || blinding_factor || metric_name)
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-7f3a2b",
                    "metric_name": "sharpe_30d",
                    "commitment_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
                    "timestamp": 1711612800.0,
                    "window_days": 30,
                }
            ]
        },
    )

    agent_id: str
    metric_name: str  # e.g. "sharpe_30d", "max_drawdown_30d", "aum"
    commitment_hash: str  # SHA3-256 hex digest
    timestamp: float
    window_days: int = 30


class AuditorAttestation(BaseModel):
    """Platform auditor's Ed25519 signature over a set of metric commitments."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-7f3a2b",
                    "auditor_id": "platform_auditor_v1",
                    "commitment_hashes": [
                        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
                        "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3",
                    ],
                    "verified_at": 1711612800.0,
                    "valid_until": 1712217600.0,
                    "data_source": "exchange_api",
                    "signature": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
                    "version": "1.0",
                    "algorithm": "ed25519-sha3-256",
                }
            ]
        }
    )

    agent_id: str
    auditor_id: str = "platform_auditor_v1"
    commitment_hashes: list[str]  # Which commitments are attested
    verified_at: float
    valid_until: float  # 7-day validity default
    data_source: str  # "self_reported", "exchange_api", "platform_verified"
    signature: str  # Ed25519 signature hex
    version: str = "1.0"  # Attestation format version for future evolution
    algorithm: str = "ed25519-sha3-256"  # Crypto algorithm identifier


class VerifiedClaim(BaseModel):
    """A claim that a metric satisfies a bound, backed by attestation.

    Example: Sharpe >= 2.0 over 30 days.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-7f3a2b",
                    "metric_name": "sharpe_30d",
                    "claim_type": "gte",
                    "bound_value": 2.0,
                    "attestation_signature": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
                    "valid_until": 1712217600.0,
                }
            ]
        },
    )

    agent_id: str
    metric_name: str
    claim_type: str  # "gte" (>=) or "lte" (<=)
    bound_value: float  # The threshold (e.g., 2.0 for Sharpe >= 2.0)
    attestation_signature: str  # Reference to the attestation
    valid_until: float


class RegistrationResult(BaseModel):
    """Result of agent registration — includes private key if auto-generated."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "identity": {
                        "agent_id": "agent-7f3a2b",
                        "public_key": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa3f4a18446b7e8c3042b58",
                        "created_at": 1711612800.0,
                        "org_id": "acme-capital",
                    },
                    "private_key": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
                }
            ]
        }
    )

    identity: AgentIdentity
    private_key: str | None = None  # Only set when keypair is auto-generated

    # Proxy fields for backward compatibility
    @property
    def agent_id(self) -> str:
        return self.identity.agent_id

    @property
    def public_key(self) -> str:
        return self.identity.public_key

    @property
    def created_at(self) -> float:
        return self.identity.created_at

    @property
    def org_id(self) -> str:
        return self.identity.org_id


class MetricSubmissionResult(BaseModel):
    """Result of metric submission — attestation + blinding factors."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "attestation": {
                        "agent_id": "agent-7f3a2b",
                        "auditor_id": "platform_auditor_v1",
                        "commitment_hashes": [
                            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
                        ],
                        "verified_at": 1711612800.0,
                        "valid_until": 1712217600.0,
                        "data_source": "exchange_api",
                        "signature": "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
                        "version": "1.0",
                        "algorithm": "ed25519-sha3-256",
                    },
                    "blinding_factors": {
                        "sharpe_30d": "c4f2e8a1b3d5f7e9a0b2c4d6e8f0a1b3c5d7e9f1a2b4c6d8e0f2a3b5c7d9e1f3",
                    },
                }
            ]
        }
    )

    attestation: AuditorAttestation
    blinding_factors: dict[str, str]  # metric_name -> blinding_factor_hex

    # Proxy fields for backward compatibility
    @property
    def agent_id(self) -> str:
        return self.attestation.agent_id

    @property
    def commitment_hashes(self) -> list[str]:
        return self.attestation.commitment_hashes

    @property
    def signature(self) -> str:
        return self.attestation.signature

    @property
    def data_source(self) -> str:
        return self.attestation.data_source

    @property
    def verified_at(self) -> float:
        return self.attestation.verified_at

    @property
    def valid_until(self) -> float:
        return self.attestation.valid_until


class AgentReputation(BaseModel):
    """Composite reputation for an agent (consumer-side trust)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-7f3a2b",
                    "timestamp": 1711612800.0,
                    "payment_reliability": 92.5,
                    "data_source_quality": 87.3,
                    "transaction_volume_score": 75.0,
                    "composite_score": 84.9,
                    "confidence": 0.82,
                }
            ]
        }
    )

    agent_id: str
    timestamp: float
    payment_reliability: float = Field(default=0.0, ge=0.0, le=100.0)
    data_source_quality: float = Field(default=0.0, ge=0.0, le=100.0)
    transaction_volume_score: float = Field(default=0.0, ge=0.0, le=100.0)
    composite_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SubIdentity(BaseModel):
    """A sub-identity (persona/role) for an agent."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sub_identity_id": "sub-agent7f3a2b-analyzer",
                    "parent_agent_id": "agent-7f3a2b",
                    "role_name": "data-analyzer",
                    "public_key": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa3f4a18446b7e8c3042b58",
                    "created_at": 1711612800.0,
                    "metadata": {"department": "data"},
                }
            ]
        }
    )

    sub_identity_id: str
    parent_agent_id: str
    role_name: str
    public_key: str
    created_at: float
    metadata: dict = Field(default_factory=dict)


class Organization(BaseModel):
    """An organization that groups agents under shared billing and management."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "id": "org-acme-001",
                    "name": "Acme Corp",
                    "owner_agent_id": "agent-7f3a2b",
                    "created_at": 1711612800.0,
                    "metadata": {"industry": "fintech"},
                }
            ]
        },
    )

    id: str
    name: str
    owner_agent_id: str
    created_at: float
    metadata: dict = Field(default_factory=dict)


class OrgMembership(BaseModel):
    """Membership record linking an agent to an organization with a role."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "org_id": "org-acme-001",
                    "agent_id": "agent-7f3a2b",
                    "role": "owner",
                    "joined_at": 1711612800.0,
                }
            ]
        },
    )

    org_id: str
    agent_id: str
    role: Literal["owner", "admin", "member"]
    joined_at: float


# Supported metric names for trading bot attestation
SUPPORTED_METRICS = {
    "sharpe_30d",
    "max_drawdown_30d",
    "pnl_30d",
    "p99_latency_ms",
    "signal_accuracy_30d",
    "win_rate_30d",
    "total_trades_30d",
    "aum",
}
