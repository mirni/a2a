"""High-level API for the Formal Gatekeeper verification system.

Orchestrates job lifecycle, Lambda invocation, proof generation, and signing.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from .models import (
    ProofArtifact,
    PropertySpec,
    VerificationJob,
    VerificationResult,
    VerificationScope,
    VerificationStatus,
)
from .storage import GatekeeperStorage


class VerifierBackend(Protocol):
    """Protocol for the Z3 verification backend (Lambda or mock)."""

    async def invoke(self, job_spec: dict[str, Any]) -> dict[str, Any]: ...


class JobNotFoundError(Exception):
    """Raised when a verification job is not found."""

    pass


class ProofNotFoundError(Exception):
    """Raised when a proof artifact is not found."""

    pass


class JobAlreadyTerminalError(Exception):
    """Raised when trying to modify a job in a terminal state."""

    pass


class IdempotencyConflictError(Exception):
    """Raised when an idempotency key collision is detected."""

    pass


# Cost: base + per-property
_BASE_COST = Decimal("5")
_PER_PROPERTY_COST = Decimal("1")

# Proof validity: 30 days
_PROOF_VALIDITY_SECONDS = 30 * 86400


@dataclass
class GatekeeperAPI:
    """High-level API for formal verification operations."""

    storage: GatekeeperStorage
    verifier: VerifierBackend | None = None
    signing_key: str = field(default="", repr=False)
    public_key: str = ""

    @classmethod
    def from_env(cls, storage: GatekeeperStorage, verifier: VerifierBackend | None = None) -> GatekeeperAPI:
        import os

        return cls(
            storage=storage,
            verifier=verifier,
            signing_key=os.environ.get("VERIFIER_SIGNING_KEY", ""),
            public_key=os.environ.get("VERIFIER_PUBLIC_KEY", ""),
        )

    async def submit_verification(
        self,
        agent_id: str,
        properties: list[dict[str, Any]],
        scope: str = "economic",
        timeout_seconds: int = 300,
        webhook_url: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> VerificationJob:
        """Submit a new verification job."""
        # Check idempotency
        if idempotency_key:
            existing = await self.storage.get_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        # Parse properties
        parsed_props = [PropertySpec(**p) for p in properties]

        # Calculate cost
        cost = _BASE_COST + _PER_PROPERTY_COST * len(parsed_props)

        job = VerificationJob(
            agent_id=agent_id,
            scope=VerificationScope(scope),
            properties=parsed_props,
            timeout_seconds=timeout_seconds,
            webhook_url=webhook_url,
            idempotency_key=idempotency_key,
            cost=cost,
            metadata=metadata or {},
        )

        job = await self.storage.create_job(job)

        # If we have a verifier backend, run the job immediately
        if self.verifier is not None:
            await self._execute_job(job)
            # Reload to get updated state
            job = await self.storage.get_job(job.id)

        return job

    async def get_verification_status(self, job_id: str) -> VerificationJob:
        """Get the current status of a verification job."""
        job = await self.storage.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {job_id}")
        return job

    async def list_verification_jobs(
        self,
        agent_id: str,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[VerificationJob]:
        """List verification jobs for an agent."""
        return await self.storage.list_jobs(
            agent_id=agent_id, status=status, limit=limit, cursor=cursor
        )

    async def cancel_verification(self, job_id: str) -> VerificationJob:
        """Cancel a pending or running verification job."""
        job = await self.storage.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {job_id}")

        if job.status in (
            VerificationStatus.COMPLETED,
            VerificationStatus.FAILED,
            VerificationStatus.CANCELLED,
        ):
            raise JobAlreadyTerminalError(
                f"Job {job_id} is in terminal state: {job.status}"
            )

        job = await self.storage.update_job_status(
            job_id, VerificationStatus.CANCELLED
        )
        return job

    async def get_proof(self, proof_id: str) -> ProofArtifact:
        """Retrieve a proof artifact."""
        proof = await self.storage.get_proof(proof_id)
        if proof is None:
            raise ProofNotFoundError(f"Proof not found: {proof_id}")
        return proof

    async def verify_proof(self, proof_hash: str) -> dict[str, Any]:
        """Verify a proof's integrity by its hash."""
        proof = await self.storage.get_proof_by_hash(proof_hash)
        if proof is None:
            return {"valid": False, "reason": "proof_not_found"}

        # Check expiry
        if time.time() > proof.valid_until:
            return {"valid": False, "reason": "proof_expired", "proof_id": proof.id}

        # Verify hash matches proof data
        computed_hash = hashlib.sha3_256(proof.proof_data.encode()).hexdigest()
        if computed_hash != proof.proof_hash:
            return {"valid": False, "reason": "hash_mismatch", "proof_id": proof.id}

        return {
            "valid": True,
            "proof_id": proof.id,
            "job_id": proof.job_id,
            "agent_id": proof.agent_id,
            "result": proof.result,
            "valid_until": proof.valid_until,
        }

    async def _execute_job(self, job: VerificationJob) -> None:
        """Execute a verification job via the verifier backend."""
        if self.verifier is None:
            return

        # Mark as running
        await self.storage.update_job_status(job.id, VerificationStatus.RUNNING)

        try:
            # Build invocation payload
            job_spec = {
                "job_id": job.id,
                "properties": [
                    {
                        "name": p.name,
                        "language": p.language,
                        "expression": p.expression,
                    }
                    for p in job.properties
                ],
                "timeout_seconds": job.timeout_seconds,
            }

            result = await self.verifier.invoke(job_spec)

            # Parse result
            overall_result = VerificationResult(result.get("result", "error"))
            property_results = result.get("property_results", [])
            proof_data = result.get("proof_data", "")
            proof_hash = result.get("proof_hash", "")

            if not proof_hash and proof_data:
                proof_hash = hashlib.sha3_256(proof_data.encode()).hexdigest()

            # Create proof artifact
            proof = ProofArtifact(
                job_id=job.id,
                agent_id=job.agent_id,
                result=overall_result,
                proof_hash=proof_hash,
                proof_data=proof_data,
                signature="",
                signer_public_key=self.public_key,
                counterexample=self._extract_counterexample(property_results),
                property_results=property_results,
                valid_until=time.time() + _PROOF_VALIDITY_SECONDS,
            )
            proof = await self.storage.create_proof(proof)

            # Update job to completed
            await self.storage.update_job_status(
                job.id,
                VerificationStatus.COMPLETED,
                result=overall_result,
                proof_artifact_id=proof.id,
            )

        except Exception:
            await self.storage.update_job_status(
                job.id,
                VerificationStatus.FAILED,
                result=VerificationResult.ERROR,
            )

    @staticmethod
    def _extract_counterexample(property_results: list[dict[str, Any]]) -> str | None:
        """Extract counterexample from violated property results."""
        for pr in property_results:
            if pr.get("result") == "violated" and pr.get("reason"):
                return pr["reason"]
            if pr.get("result") == "satisfied" and pr.get("model"):
                return pr["model"]
        return None
