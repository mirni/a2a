"""High-level API for agent identity operations.

Orchestrates crypto, storage, and attestation workflows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .crypto import AgentCrypto
from .models import (
    SUPPORTED_METRICS,
    AgentIdentity,
    AgentReputation,
    AuditorAttestation,
    MetricCommitment,
    VerifiedClaim,
)
from .storage import IdentityStorage


class AgentNotFoundError(Exception):
    """Raised when an agent_id is not found in storage."""
    pass


class InvalidMetricError(Exception):
    """Raised when a metric name is not in the supported set."""
    pass


# Default attestation validity: 7 days
_DEFAULT_VALIDITY_SECONDS = 7 * 24 * 3600


@dataclass
class IdentityAPI:
    """High-level API for agent identity operations.

    Attributes:
        storage: IdentityStorage for data access.
        auditor_private_key: Hex-encoded Ed25519 private key for the platform auditor.
        auditor_public_key: Hex-encoded Ed25519 public key for the platform auditor.
    """

    storage: IdentityStorage
    auditor_private_key: str = field(default="", repr=False)
    auditor_public_key: str = ""

    def __post_init__(self) -> None:
        """Auto-generate auditor keypair if not provided."""
        if not self.auditor_private_key:
            priv, pub = AgentCrypto.generate_keypair()
            self.auditor_private_key = priv
            self.auditor_public_key = pub

    async def register_agent(
        self, agent_id: str, public_key: str | None = None
    ) -> AgentIdentity:
        """Register agent identity. Auto-generates keypair if no public_key given.

        Args:
            agent_id: Unique agent identifier.
            public_key: Optional Ed25519 public key hex. If None, a keypair is generated.

        Returns:
            The registered AgentIdentity (public_key only; private key returned inline
            when auto-generated but NOT stored).
        """
        if public_key is None:
            _private_key, public_key = AgentCrypto.generate_keypair()

        identity = AgentIdentity(
            agent_id=agent_id,
            public_key=public_key,
            created_at=time.time(),
        )
        return await self.storage.store_identity(identity)

    async def get_identity(self, agent_id: str) -> AgentIdentity | None:
        """Get the identity for an agent."""
        return await self.storage.get_identity(agent_id)

    async def verify_agent(
        self, agent_id: str, message: bytes, signature_hex: str
    ) -> bool:
        """Verify that a message was signed by the claimed agent.

        Args:
            agent_id: The agent who claims to have signed.
            message: The original message bytes.
            signature_hex: The claimed Ed25519 signature.

        Returns:
            True if the signature is valid for this agent's public key.

        Raises:
            AgentNotFoundError: If the agent_id is not registered.
        """
        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        return AgentCrypto.verify(identity.public_key, message, signature_hex)

    async def submit_metrics(
        self,
        agent_id: str,
        metrics: dict[str, float],
        data_source: str = "self_reported",
    ) -> AuditorAttestation:
        """Agent submits metrics. Platform creates commitments and attestation.

        For each metric, a hiding commitment is created. The platform auditor then
        signs all commitment hashes together with the attestation metadata.

        Args:
            agent_id: The agent submitting metrics.
            metrics: Dict of metric_name -> value (e.g. {"sharpe_30d": 2.35}).
            data_source: "self_reported", "exchange_api", or "platform_verified".

        Returns:
            The created AuditorAttestation.

        Raises:
            AgentNotFoundError: If the agent is not registered.
            InvalidMetricError: If a metric name is not supported.
        """
        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")

        # Validate metric names
        for name in metrics:
            if name not in SUPPORTED_METRICS:
                raise InvalidMetricError(
                    f"Unsupported metric: {name}. "
                    f"Supported: {sorted(SUPPORTED_METRICS)}"
                )

        now = time.time()
        commitment_hashes: list[str] = []

        # Create commitments for each metric
        for metric_name, value in metrics.items():
            commit_hash, _blinding = AgentCrypto.create_commitment(value, metric_name)
            commitment = MetricCommitment(
                agent_id=agent_id,
                metric_name=metric_name,
                commitment_hash=commit_hash,
                timestamp=now,
            )
            await self.storage.store_commitment(commitment)
            commitment_hashes.append(commit_hash)

        # Create attestation
        valid_until = now + _DEFAULT_VALIDITY_SECONDS
        signature = AgentCrypto.sign_attestation(
            self.auditor_private_key,
            agent_id,
            commitment_hashes,
            now,
            valid_until,
            data_source,
        )

        attestation = AuditorAttestation(
            agent_id=agent_id,
            commitment_hashes=commitment_hashes,
            verified_at=now,
            valid_until=valid_until,
            data_source=data_source,
            signature=signature,
        )
        attestation_id = await self.storage.store_attestation(attestation)

        # Create verified claims based on the submitted metrics
        for metric_name, value in metrics.items():
            # For metrics where higher is better, create "gte" claims
            # For metrics where lower is better (drawdown, latency), create "lte" claims
            lower_is_better = metric_name in {"max_drawdown_30d", "p99_latency_ms"}
            claim_type = "lte" if lower_is_better else "gte"

            claim = VerifiedClaim(
                agent_id=agent_id,
                metric_name=metric_name,
                claim_type=claim_type,
                bound_value=value,
                attestation_signature=signature,
                valid_until=valid_until,
            )
            await self.storage.store_claim(claim, attestation_id)

        return attestation

    async def get_verified_claims(self, agent_id: str) -> list[VerifiedClaim]:
        """Get all valid (non-expired) verified claims for an agent."""
        return await self.storage.get_claims(agent_id, valid_only=True)

    async def get_reputation(self, agent_id: str) -> AgentReputation | None:
        """Get agent's consumer-side reputation score."""
        return await self.storage.get_latest_reputation(agent_id)

    async def compute_reputation(self, agent_id: str) -> AgentReputation:
        """Recompute agent reputation from available data.

        In MVP, this computes a simple composite from:
        - Number of valid attestations (proxy for activity)
        - Data source quality (platform_verified > exchange_api > self_reported)
        - Attestation recency

        A full implementation would pull from payment history, dispute records, etc.
        """
        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")

        attestations = await self.storage.get_attestations(agent_id, valid_only=True)
        now = time.time()

        # Payment reliability: based on attestation count (proxy in MVP)
        # More attestations = more reliable (up to 10 = 100)
        payment_reliability = min(len(attestations) * 10.0, 100.0)

        # Dispute rate: inverse of self-reported ratio (platform-verified is best)
        source_scores = {
            "platform_verified": 100.0,
            "exchange_api": 70.0,
            "self_reported": 40.0,
        }
        if attestations:
            dispute_rate = sum(
                source_scores.get(a.data_source, 40.0) for a in attestations
            ) / len(attestations)
        else:
            dispute_rate = 0.0

        # Transaction volume: based on total commitments
        commitments = await self.storage.get_commitments(agent_id)
        transaction_volume_score = min(len(commitments) * 5.0, 100.0)

        # Composite: weighted average
        composite = (
            payment_reliability * 0.4
            + dispute_rate * 0.3
            + transaction_volume_score * 0.3
        )

        # Confidence: based on data age and volume
        if attestations:
            newest = max(a.verified_at for a in attestations)
            age_hours = (now - newest) / 3600
            recency_factor = max(0.0, 1.0 - age_hours / (7 * 24))  # Decay over 7 days
            volume_factor = min(len(attestations) / 5.0, 1.0)
            confidence = recency_factor * volume_factor
        else:
            confidence = 0.0

        reputation = AgentReputation(
            agent_id=agent_id,
            timestamp=now,
            payment_reliability=payment_reliability,
            dispute_rate=dispute_rate,
            transaction_volume_score=transaction_volume_score,
            composite_score=composite,
            confidence=min(confidence, 1.0),
        )
        await self.storage.store_reputation(reputation)
        return reputation
