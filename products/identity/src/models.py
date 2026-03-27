"""Pydantic models for the Agent Identity system.

Covers cryptographic identity (Ed25519 key pairs), metric commitments
(HMAC-based hiding commitments), auditor attestations, verified claims,
and consumer-side reputation.

All timestamps are Unix floats (time.time()).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentIdentity(BaseModel):
    """Cryptographic identity for an agent (Ed25519 key pair)."""
    agent_id: str
    public_key: str  # Ed25519 public key hex
    created_at: float
    org_id: str = "default"


class MetricCommitment(BaseModel):
    """A hiding commitment to a numeric metric value.

    commitment_hash = SHA3-256(value_scaled_bytes || blinding_factor || metric_name)
    """
    agent_id: str
    metric_name: str  # e.g. "sharpe_30d", "max_drawdown_30d", "aum"
    commitment_hash: str  # SHA3-256 hex digest
    timestamp: float
    window_days: int = 30


class AuditorAttestation(BaseModel):
    """Platform auditor's Ed25519 signature over a set of metric commitments."""
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
    agent_id: str
    metric_name: str
    claim_type: str  # "gte" (>=) or "lte" (<=)
    bound_value: float  # The threshold (e.g., 2.0 for Sharpe >= 2.0)
    attestation_signature: str  # Reference to the attestation
    valid_until: float


class RegistrationResult(BaseModel):
    """Result of agent registration — includes private key if auto-generated."""
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
    agent_id: str
    timestamp: float
    payment_reliability: float = Field(default=0.0, ge=0.0, le=100.0)
    data_source_quality: float = Field(default=0.0, ge=0.0, le=100.0)
    transaction_volume_score: float = Field(default=0.0, ge=0.0, le=100.0)
    composite_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


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
