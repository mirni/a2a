"""High-level API for agent identity operations.

Orchestrates crypto, storage, and attestation workflows.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from .crypto import AgentCrypto, MerkleTree
from .models import (
    SUPPORTED_METRICS,
    AgentIdentity,
    AgentReputation,
    AuditorAttestation,
    MetricCommitment,
    MetricSubmissionResult,
    RegistrationResult,
    SubIdentity,
    VerifiedClaim,
)
from .storage import IdentityStorage


class AgentNotFoundError(Exception):
    """Raised when an agent_id is not found in storage."""

    pass


class InvalidMetricError(Exception):
    """Raised when a metric name is not in the supported set."""

    pass


class AgentAlreadyExistsError(Exception):
    """Raised when trying to register an agent_id that already exists."""

    pass


# Default attestation validity: 7 days
_DEFAULT_VALIDITY_SECONDS = 7 * 24 * 3600

# Data source trust tier weights (PRD 011)
DATA_SOURCE_WEIGHTS: dict[str, float] = {
    "platform_verified": 1.0,
    "exchange_api": 0.7,
    "agent_signed": 0.5,
    "self_reported": 0.4,
}


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
    _custom_metrics: set = field(default_factory=set, init=False, repr=False)
    _key_history: list = field(default_factory=list, init=False, repr=False)
    _payment_signals: dict = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Auto-generate auditor keypair if not provided."""
        if not self.auditor_private_key:
            priv, pub = AgentCrypto.generate_keypair()
            self.auditor_private_key = priv
            self.auditor_public_key = pub

    @classmethod
    def from_env(cls, storage: IdentityStorage) -> IdentityAPI:
        """Create IdentityAPI loading auditor keys from environment.

        Reads AUDITOR_PRIVATE_KEY and AUDITOR_PUBLIC_KEY env vars.
        Falls back to auto-generation if not set.
        """
        import os

        priv = os.environ.get("AUDITOR_PRIVATE_KEY", "")
        pub = os.environ.get("AUDITOR_PUBLIC_KEY", "")
        return cls(storage=storage, auditor_private_key=priv, auditor_public_key=pub)

    async def register_agent(self, agent_id: str, public_key: str | None = None) -> RegistrationResult:
        """Register agent identity. Auto-generates keypair if no public_key given.

        Args:
            agent_id: Unique agent identifier.
            public_key: Optional Ed25519 public key hex. If None, a keypair is generated.

        Returns:
            RegistrationResult with identity and private_key (if auto-generated).
            Private key is returned one-time to the caller and never stored server-side.
        """
        # Check for duplicate
        existing = await self.storage.get_identity(agent_id)
        if existing is not None:
            raise AgentAlreadyExistsError(f"Agent already exists: {agent_id}")

        private_key: str | None = None
        if public_key is None:
            private_key, public_key = AgentCrypto.generate_keypair()

        identity = AgentIdentity(
            agent_id=agent_id,
            public_key=public_key,
            created_at=time.time(),
        )
        stored = await self.storage.store_identity(identity)
        return RegistrationResult(identity=stored, private_key=private_key)

    async def get_identity(self, agent_id: str) -> AgentIdentity | None:
        """Get the identity for an agent."""
        return await self.storage.get_identity(agent_id)

    async def verify_agent(self, agent_id: str, message: bytes, signature_hex: str) -> bool:
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
        signature: str | None = None,
        nonce: str | None = None,
    ) -> MetricSubmissionResult:
        """Agent submits metrics. Platform creates commitments and attestation.

        For each metric, a hiding commitment is created. The platform auditor then
        signs all commitment hashes together with the attestation metadata.
        Blinding factors are stored and returned so the agent can later reveal values.

        If a valid Ed25519 signature and unused nonce are provided, the submission
        is upgraded to ``data_source='agent_signed'``.

        Args:
            agent_id: The agent submitting metrics.
            metrics: Dict of metric_name -> value (e.g. {"sharpe_30d": 2.35}).
            data_source: "self_reported", "exchange_api", or "platform_verified".
            signature: Optional Ed25519 signature hex over canonical JSON of metrics+nonce.
            nonce: Optional unique nonce for replay protection.

        Returns:
            MetricSubmissionResult with attestation and blinding_factors.

        Raises:
            AgentNotFoundError: If the agent is not registered.
            InvalidMetricError: If a metric name is not supported.
            ValueError: If nonce has already been used.
        """
        import json as _json

        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")

        # Validate metric names against base + custom metrics
        all_metrics = self.get_supported_metrics()
        for name in metrics:
            if name not in all_metrics:
                raise InvalidMetricError(f"Unsupported metric: {name}. Supported: {sorted(all_metrics)}")

        # Signature verification (PRD 011)
        if signature and nonce:
            # Check nonce replay
            if await self.storage.is_nonce_used(nonce):
                raise ValueError(f"Nonce already used: {nonce}")

            # Verify Ed25519 signature over canonical JSON
            canonical = _json.dumps(
                {"metrics": metrics, "nonce": nonce},
                sort_keys=True,
                separators=(",", ":"),
            )
            if AgentCrypto.verify(identity.public_key, canonical.encode(), signature):
                data_source = "agent_signed"

            # Store nonce regardless of signature validity
            await self.storage.store_nonce(nonce, agent_id)

        now = time.time()
        commitment_hashes: list[str] = []
        blinding_factors: dict[str, str] = {}

        # Create commitments for each metric
        for metric_name, value in metrics.items():
            commit_hash, blinding = AgentCrypto.create_commitment(value, metric_name)
            commitment = MetricCommitment(
                agent_id=agent_id,
                metric_name=metric_name,
                commitment_hash=commit_hash,
                timestamp=now,
            )
            await self.storage.store_commitment(commitment)
            await self.storage.store_commitment_secret(agent_id, metric_name, commit_hash, blinding)
            commitment_hashes.append(commit_hash)
            blinding_factors[metric_name] = blinding

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

        return MetricSubmissionResult(
            attestation=attestation,
            blinding_factors=blinding_factors,
        )

    async def reveal_commitment(
        self,
        agent_id: str,
        metric_name: str,
        value: float,
        blinding_factor: str,
    ) -> dict:
        """Reveal (open) a commitment to prove the committed value.

        Verifies that the provided value and blinding factor match a stored
        commitment hash. If verified, returns the revealed value.

        Args:
            agent_id: The agent who created the commitment.
            metric_name: The metric name.
            value: The claimed value.
            blinding_factor: The hex-encoded blinding factor.

        Returns:
            Dict with: verified (bool), metric_name, value.
            If no matching commitment found, verified=False.
        """
        secrets = await self.storage.get_commitment_secrets(agent_id, metric_name)
        if not secrets:
            return {"verified": False, "metric_name": metric_name, "value": value}

        # Try to verify against the most recent commitment
        for secret in secrets:
            commitment_hash = secret["commitment_hash"]
            if AgentCrypto.verify_commitment(value, metric_name, blinding_factor, commitment_hash):
                return {
                    "verified": True,
                    "metric_name": metric_name,
                    "value": value,
                    "commitment_hash": commitment_hash,
                }

        return {"verified": False, "metric_name": metric_name, "value": value}

    async def revoke_attestation(self, attestation_id: int, reason: str = "") -> dict:
        """Revoke an attestation, invalidating all linked claims.

        Args:
            attestation_id: The storage row ID of the attestation.
            reason: Human-readable reason for revocation.

        Returns:
            Dict with revoked (bool) and attestation_id.
        """
        success = await self.storage.revoke_attestation(attestation_id, reason)
        return {"revoked": success, "attestation_id": attestation_id}

    async def get_verified_claims(self, agent_id: str) -> list[VerifiedClaim]:
        """Get all valid (non-expired, non-revoked) verified claims for an agent."""
        return await self.storage.get_claims(agent_id, valid_only=True)

    async def get_reputation(self, agent_id: str) -> AgentReputation | None:
        """Get agent's consumer-side reputation score."""
        return await self.storage.get_latest_reputation(agent_id)

    async def search_agents_by_metrics(
        self,
        metric_name: str,
        min_value: float | None = None,
        max_value: float | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Search for agents with verified claims matching metric criteria.

        For "higher is better" metrics (sharpe, pnl, accuracy, win_rate, trades, aum),
        use min_value to find agents claiming >= that value.
        For "lower is better" metrics (max_drawdown, latency), use max_value.

        Returns list of dicts with agent_id, metric_name, claim_type, bound_value.
        """
        all_metrics = self.get_supported_metrics()
        if metric_name not in all_metrics:
            raise InvalidMetricError(f"Unsupported metric: {metric_name}. Supported: {sorted(all_metrics)}")

        claims = await self.storage.search_claims(
            metric_name=metric_name,
            min_value=min_value,
            max_value=max_value,
            limit=limit,
        )
        # Deduplicate by agent_id (keep best claim per agent)
        seen: dict[str, VerifiedClaim] = {}
        for c in claims:
            if c.agent_id not in seen:
                seen[c.agent_id] = c
        return [
            {
                "agent_id": c.agent_id,
                "metric_name": c.metric_name,
                "claim_type": c.claim_type,
                "bound_value": c.bound_value,
                "valid_until": c.valid_until,
            }
            for c in seen.values()
        ]

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

        # Payment reliability: use actual payment signals if available,
        # otherwise fall back to attestation count as proxy
        signals = self._payment_signals.get(agent_id, {})
        completed = signals.get("payment_completed", 0)
        disputes = signals.get("dispute_opened", 0)
        if completed + disputes > 0:
            # Real payment data: reliability = completed / total * 100
            payment_reliability = (completed / (completed + disputes)) * 100.0
        else:
            # Proxy: more attestations = more reliable (up to 10 = 100)
            payment_reliability = min(len(attestations) * 10.0, 100.0)

        # Data source quality: weighted by verification tier
        source_scores = {
            "platform_verified": 100.0,
            "exchange_api": 70.0,
            "self_reported": 40.0,
        }
        if attestations:
            data_source_quality = sum(source_scores.get(a.data_source, 40.0) for a in attestations) / len(attestations)
        else:
            data_source_quality = 0.0

        # Transaction volume: based on total commitments
        commitments = await self.storage.get_commitments(agent_id)
        transaction_volume_score = min(len(commitments) * 5.0, 100.0)

        # Composite: weighted average
        composite = payment_reliability * 0.4 + data_source_quality * 0.3 + transaction_volume_score * 0.3

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
            data_source_quality=data_source_quality,
            transaction_volume_score=transaction_volume_score,
            composite_score=composite,
            confidence=min(confidence, 1.0),
        )
        await self.storage.store_reputation(reputation)
        return reputation

    async def build_claim_chain(self, agent_id: str) -> dict:
        """Build a Merkle tree from all valid attestations for an agent.

        Each attestation's signature is hashed (SHA3-256) to create a leaf.
        The leaves are ordered by verified_at (oldest first) and assembled
        into a Merkle tree. The resulting chain is stored for later proof
        generation.

        Args:
            agent_id: The agent whose attestations to chain.

        Returns:
            Dict with keys: merkle_root, leaf_count, period_start, period_end, chain_id.

        Raises:
            AgentNotFoundError: If the agent_id is not registered.
        """
        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")

        attestations = await self.storage.get_attestations(agent_id, valid_only=True)

        if not attestations:
            empty_root = hashlib.sha3_256(b"").hexdigest()
            now = time.time()
            chain_id = await self.storage.store_claim_chain(
                agent_id=agent_id,
                merkle_root=empty_root,
                leaf_hashes=[],
                period_start=now,
                period_end=now,
            )
            return {
                "merkle_root": empty_root,
                "leaf_count": 0,
                "period_start": now,
                "period_end": now,
                "chain_id": chain_id,
            }

        # Sort by verified_at ascending (oldest first) for deterministic ordering
        attestations.sort(key=lambda a: a.verified_at)

        # Create leaf hashes: SHA3-256 of each attestation's signature
        leaf_hashes = [hashlib.sha3_256(a.signature.encode()).hexdigest() for a in attestations]

        merkle_root = MerkleTree.compute_root(leaf_hashes)
        period_start = attestations[0].verified_at
        period_end = attestations[-1].verified_at

        chain_id = await self.storage.store_claim_chain(
            agent_id=agent_id,
            merkle_root=merkle_root,
            leaf_hashes=leaf_hashes,
            period_start=period_start,
            period_end=period_end,
        )

        return {
            "merkle_root": merkle_root,
            "leaf_count": len(leaf_hashes),
            "period_start": period_start,
            "period_end": period_end,
            "chain_id": chain_id,
        }

    # ------------------------------------------------------------------
    # Sub-identity management
    # ------------------------------------------------------------------

    async def create_sub_identity(
        self,
        parent_agent_id: str,
        role_name: str,
        public_key: str | None = None,
        metadata: dict | None = None,
    ) -> SubIdentity:
        """Create a sub-identity (persona/role) for a parent agent.

        Args:
            parent_agent_id: The parent agent who owns this sub-identity.
            role_name: Role name for the sub-identity.
            public_key: Optional Ed25519 public key hex. Auto-generated if None.
            metadata: Optional metadata dict.

        Returns:
            SubIdentity with generated sub_identity_id and keypair.

        Raises:
            AgentNotFoundError: If parent agent is not registered.
            ValueError: If role_name already exists for this parent.
        """
        parent = await self.storage.get_identity(parent_agent_id)
        if parent is None:
            raise AgentNotFoundError(f"Agent not found: {parent_agent_id}")

        # Check for duplicate role
        existing = await self.storage.list_sub_identities(parent_agent_id)
        for sub in existing:
            if sub["role_name"] == role_name:
                raise ValueError(f"Sub-identity with role '{role_name}' already exists for {parent_agent_id}")

        if public_key is None:
            _priv, public_key = AgentCrypto.generate_keypair()

        sub_id = f"sub-{parent_agent_id}-{role_name}"
        await self.storage.store_sub_identity(
            sub_identity_id=sub_id,
            parent_agent_id=parent_agent_id,
            role_name=role_name,
            public_key=public_key,
            metadata=metadata,
        )
        return SubIdentity(
            sub_identity_id=sub_id,
            parent_agent_id=parent_agent_id,
            role_name=role_name,
            public_key=public_key,
            created_at=time.time(),
            metadata=metadata or {},
        )

    async def get_sub_identity(self, sub_identity_id: str) -> SubIdentity | None:
        """Get a sub-identity by its ID."""
        row = await self.storage.get_sub_identity(sub_identity_id)
        if row is None:
            return None
        return SubIdentity(**row)

    async def list_sub_identities(self, parent_agent_id: str) -> list[SubIdentity]:
        """List all sub-identities for a parent agent."""
        rows = await self.storage.list_sub_identities(parent_agent_id)
        return [SubIdentity(**r) for r in rows]

    async def delete_sub_identity(self, sub_identity_id: str) -> None:
        """Delete a sub-identity. No-op if not found."""
        await self.storage.delete_sub_identity(sub_identity_id)

    # ------------------------------------------------------------------
    # TODO-14: Configurable metrics
    # ------------------------------------------------------------------

    def register_custom_metric(self, metric_name: str) -> None:
        """Register a custom metric name for use in submissions."""
        self._custom_metrics.add(metric_name)

    def deregister_custom_metric(self, metric_name: str) -> None:
        """Remove a custom metric from the supported set."""
        self._custom_metrics.discard(metric_name)

    def get_supported_metrics(self) -> set[str]:
        """Return the full set of supported metric names (base + custom)."""
        return SUPPORTED_METRICS | self._custom_metrics

    # ------------------------------------------------------------------
    # TODO-15: Auditor key rotation
    # ------------------------------------------------------------------

    async def rotate_auditor_key(self) -> str:
        """Rotate the auditor keypair. Archives the old key in history.

        Returns:
            The new auditor public key hex.
        """
        # Archive old key
        self._key_history.append(
            {
                "public_key": self.auditor_public_key,
                "retired_at": time.time(),
            }
        )

        # Generate new keypair
        priv, pub = AgentCrypto.generate_keypair()
        self.auditor_private_key = priv
        self.auditor_public_key = pub
        return pub

    def get_auditor_key_history(self) -> list[dict]:
        """Return the history of retired auditor public keys."""
        return list(self._key_history)

    # ------------------------------------------------------------------
    # TODO-16: W3C VC alignment
    # ------------------------------------------------------------------

    def export_attestation_as_vc(self, attestation: AuditorAttestation) -> dict:
        """Export an attestation in W3C Verifiable Credential format.

        Returns a JSON-serializable dict conforming to the VC data model.
        """
        return {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential", "MetricAttestation"],
            "issuer": f"did:a2a:{attestation.auditor_id}",
            "issuanceDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(attestation.verified_at)),
            "expirationDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(attestation.valid_until)),
            "credentialSubject": {
                "id": f"did:a2a:{attestation.agent_id}",
                "claims": attestation.commitment_hashes,
                "dataSource": attestation.data_source,
            },
            "proof": {
                "type": "Ed25519Signature2020",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(attestation.verified_at)),
                "proofPurpose": "assertionMethod",
                "verificationMethod": f"did:a2a:{attestation.auditor_id}#key-1",
                "proofValue": attestation.signature,
                "algorithm": attestation.algorithm,
            },
        }

    # ------------------------------------------------------------------
    # TODO-17: Merkle proof endpoint
    # ------------------------------------------------------------------

    async def get_inclusion_proof(self, chain_id: int, attestation_index: int) -> dict:
        """Get a Merkle inclusion proof for a specific attestation in a chain.

        Args:
            chain_id: The claim chain row ID.
            attestation_index: Index of the attestation (leaf) in the chain.

        Returns:
            Dict with leaf_hash, proof (list of {sibling, position}), and root.
        """
        import json as _json

        chains = await self.storage.get_claim_chains_by_id(chain_id)
        if not chains:
            raise ValueError(f"Chain not found: {chain_id}")

        chain = chains[0]
        leaf_hashes = _json.loads(chain["leaf_hashes"])
        root = chain["merkle_root"]

        if attestation_index < 0 or attestation_index >= len(leaf_hashes):
            raise IndexError(
                f"attestation_index {attestation_index} out of range for chain with {len(leaf_hashes)} leaves"
            )

        proof_tuples = MerkleTree.compute_proof(leaf_hashes, attestation_index)
        proof = [{"sibling": sibling, "position": position} for sibling, position in proof_tuples]

        return {
            "leaf_hash": leaf_hashes[attestation_index],
            "proof": proof,
            "root": root,
            "chain_id": chain_id,
            "attestation_index": attestation_index,
        }

    # ------------------------------------------------------------------
    # Time-series ingestion & query (PRD 012)
    # ------------------------------------------------------------------

    async def ingest_timeseries(
        self,
        agent_id: str,
        metrics: dict[str, float],
        data_source: str = "self_reported",
        signature: str | None = None,
        nonce: str | None = None,
        timestamp: float | None = None,
    ) -> dict:
        """Ingest metric data points into the time-series store.

        Validates metric names, optionally verifies signature, then stores
        each valid metric. Invalid metric names are skipped (counted as rejected).

        Returns:
            Dict with accepted, rejected counts.
        """
        import json as _json

        identity = await self.storage.get_identity(agent_id)
        if identity is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")

        # Signature verification (reuses PRD 011 logic)
        if signature and nonce:
            if await self.storage.is_nonce_used(nonce):
                raise ValueError(f"Nonce already used: {nonce}")
            canonical = _json.dumps(
                {"metrics": metrics, "nonce": nonce},
                sort_keys=True,
                separators=(",", ":"),
            )
            if AgentCrypto.verify(identity.public_key, canonical.encode(), signature):
                data_source = "agent_signed"
            await self.storage.store_nonce(nonce, agent_id)

        all_metrics = self.get_supported_metrics()
        ts = timestamp or time.time()
        accepted = 0
        rejected = 0

        for metric_name, value in metrics.items():
            if metric_name not in all_metrics:
                rejected += 1
                continue
            await self.storage.store_timeseries(
                agent_id=agent_id,
                metric_name=metric_name,
                value=value,
                timestamp=ts,
                data_source=data_source,
            )
            accepted += 1

        return {"accepted": accepted, "rejected": rejected}

    async def query_agent_timeseries(
        self,
        agent_id: str,
        metric_name: str,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query time-series data for an agent+metric."""
        return await self.storage.query_timeseries(
            agent_id=agent_id,
            metric_name=metric_name,
            since=since,
            limit=limit,
        )

    async def get_metric_deltas(self, agent_id: str, metric_name: str | None = None) -> dict:
        """Compare latest value to previous value for each metric.

        If metric_name is given, returns deltas for that metric only.
        Otherwise returns deltas for all metrics with >=2 data points.
        """
        result: dict[str, dict] = {}
        metric_names = [metric_name] if metric_name else list(self.get_supported_metrics())

        for name in metric_names:
            rows = await self.storage.query_timeseries(agent_id, name, limit=2)
            if len(rows) < 2:
                continue
            current = rows[0]["value"]
            previous = rows[1]["value"]
            result[name] = {
                "current": current,
                "previous": previous,
                "absolute_delta": current - previous,
                "relative_delta": ((current - previous) / previous * 100) if previous != 0 else 0.0,
            }
        return result

    async def get_metric_averages(self, agent_id: str, period: str = "30d") -> dict:
        """Return pre-computed aggregates for an agent, keyed by metric name."""
        result: dict[str, dict] = {}
        for name in self.get_supported_metrics():
            agg = await self.storage.get_aggregates(agent_id, name, period)
            if agg is not None:
                result[name] = agg
        return result

    # ------------------------------------------------------------------
    # TODO-18: Reputation integration with payment/dispute data
    # ------------------------------------------------------------------

    async def record_payment_signal(self, agent_id: str, signal_type: str, count: int = 1) -> None:
        """Record a payment/dispute signal for reputation calculation.

        Args:
            agent_id: The agent to record the signal for.
            signal_type: 'payment_completed' or 'dispute_opened'.
            count: Number of events to record.
        """
        if agent_id not in self._payment_signals:
            self._payment_signals[agent_id] = {
                "payment_completed": 0,
                "dispute_opened": 0,
            }
        if signal_type in self._payment_signals[agent_id]:
            self._payment_signals[agent_id][signal_type] += count
