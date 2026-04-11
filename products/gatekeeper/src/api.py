"""High-level API for the Formal Gatekeeper verification system.

Orchestrates job lifecycle, Lambda invocation, proof generation, and signing.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

logger = logging.getLogger("a2a.gatekeeper")

from .models import (
    ProofArtifact,
    PropertySpec,
    VerificationJob,
    VerificationResult,
    VerificationScope,
    VerificationStatus,
)
from .policy import JsonPolicy, PolicyCompileError, compile_policy_to_smt2
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


class InvalidPolicyError(ValueError):
    """Raised when a submitted JSON policy fails to parse or compile."""

    pass


def _compile_json_policy_expression(expression: str) -> str:
    """Parse and compile a JSON policy string to an SMT-LIB2 expression.

    Wraps :func:`products.gatekeeper.src.policy.compile_policy_to_smt2`
    with JSON-parse error handling so the caller only needs to handle one
    exception type.

    Raises :class:`InvalidPolicyError` on any parse / schema / compile
    failure, with a caller-friendly message.
    """
    import json as _json

    try:
        data = _json.loads(expression)
    except _json.JSONDecodeError as exc:
        raise InvalidPolicyError(f"json_policy expression is not valid JSON: {exc.msg}") from exc

    try:
        policy = JsonPolicy.model_validate(data)
    except Exception as exc:
        raise InvalidPolicyError(f"json_policy failed schema validation: {exc}") from exc

    try:
        return compile_policy_to_smt2(policy)
    except PolicyCompileError as exc:
        raise InvalidPolicyError(f"json_policy failed to compile: {exc}") from exc


# ---------------------------------------------------------------------------
# Pricing (v1.2.4 repricing)
# ---------------------------------------------------------------------------
#
# Formula:
#   quoted_cost = _BASE_COST + _PER_PROPERTY_COST * len(properties)
#   final_cost  = quoted_cost + _compute_solver_surcharge(duration_ms)
#
# Rationale:
#   v1.2.3 and earlier charged a flat 5 + N credits. That left complex
#   proofs heavily underpriced relative to their AWS Lambda cost and
#   opportunity cost (a 60s / 100-property job charged only $1.05).
#   v1.2.4 doubles the base and per-property floor and adds a heavy-tail
#   surcharge tied to solver wall-time so price tracks solver work.
#
#   For trivial proofs (<1s warm) the user still pays a low floor; for
#   heavy proofs the bill grows proportionally. Free tier is intentionally
#   absent — every proof is a billable event.
_BASE_COST = Decimal("10")
_PER_PROPERTY_COST = Decimal("2")

# Heavy-tail solver-time surcharge.
#   - No surcharge for the first 1000 ms of solver time.
#   - Above that, 1 credit per 500 ms (rounded up).
#   - Example: 1001 ms → 1 credit; 1500 ms → 1; 1501 ms → 2; 60000 ms → 118.
_SOLVER_TIME_FREE_MS = 1000
_SOLVER_TIME_INCREMENT_MS = 500
_SOLVER_TIME_COST_PER_INCREMENT = Decimal("1")


def _compute_solver_surcharge(duration_ms: int) -> Decimal:
    """Return the heavy-tail surcharge in credits for a given solver duration.

    Pure function — no state, no I/O. Covered by
    ``tests/test_api.py::TestPricingV124::test_solver_surcharge_helper_bounds``.
    """
    if duration_ms is None or duration_ms <= _SOLVER_TIME_FREE_MS:
        return Decimal("0")
    overflow_ms = duration_ms - _SOLVER_TIME_FREE_MS
    # Ceiling division: (a + b - 1) // b
    increments = (overflow_ms + _SOLVER_TIME_INCREMENT_MS - 1) // _SOLVER_TIME_INCREMENT_MS
    return _SOLVER_TIME_COST_PER_INCREMENT * Decimal(increments)


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
                if existing.agent_id != agent_id:
                    raise IdempotencyConflictError(f"Idempotency key '{idempotency_key}' belongs to a different agent")
                return existing

        # Parse properties
        parsed_props = [PropertySpec(**p) for p in properties]

        # Eagerly validate json_policy expressions so integrators get a
        # 4xx response at submission time instead of a deferred FAILED
        # job. We only validate here; the compiled SMT2 is produced
        # just-in-time in ``_execute_job`` so the original policy is
        # preserved in storage for audit / display.
        for prop in parsed_props:
            if prop.language == "json_policy":
                _compile_json_policy_expression(prop.expression)

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

        # v1.2.4 P1: concurrent idempotency race — two callers with the
        # same idem key can both pass the get_job_by_idempotency_key
        # check above and race to INSERT. The DB UNIQUE constraint on
        # ``idempotency_key`` protects the invariant; we catch the
        # IntegrityError here and re-lookup so both callers observe the
        # winning job instead of one seeing an exception.
        try:
            job = await self.storage.create_job(job)
        except Exception as exc:  # noqa: BLE001
            if idempotency_key is None:
                raise
            # Only swallow integrity-style errors for idempotency races.
            error_text = str(exc).lower()
            if "unique" not in error_text and "constraint" not in error_text:
                raise
            existing = await self.storage.get_job_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            if existing.agent_id != agent_id:
                raise IdempotencyConflictError(
                    f"Idempotency key '{idempotency_key}' belongs to a different agent"
                ) from exc
            return existing

        # If we have a verifier backend, run the job immediately
        if self.verifier is not None:
            await self._execute_job(job)
            # Reload to get updated state
            updated = await self.storage.get_job(job.id)
            if updated is not None:
                job = updated

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
        return await self.storage.list_jobs(agent_id=agent_id, status=status, limit=limit, cursor=cursor)

    async def cancel_verification(self, job_id: str) -> VerificationJob:
        """Cancel a pending or running verification job."""
        job = await self.storage.get_job(job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {job_id}")

        if job.status in (
            VerificationStatus.COMPLETED,
            VerificationStatus.FAILED,
            VerificationStatus.CANCELLED,
            VerificationStatus.TIMEOUT,
        ):
            raise JobAlreadyTerminalError(f"Job {job_id} is in terminal state: {job.status}")

        updated = await self.storage.update_job_status(job_id, VerificationStatus.CANCELLED)
        if updated is None:
            raise JobNotFoundError(f"Job not found after update: {job_id}")
        return updated

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
            # Build invocation payload. For ``json_policy`` properties we
            # compile the stored JSON expression to SMT-LIB2 just-in-time
            # so the verifier backend only ever sees a single language.
            compiled_props: list[dict[str, Any]] = []
            for p in job.properties:
                expression = p.expression
                language = p.language
                if language == "json_policy":
                    expression = _compile_json_policy_expression(p.expression)
                    language = "z3_smt2"
                compiled_props.append(
                    {
                        "name": p.name,
                        "language": language,
                        "expression": expression,
                    }
                )

            job_spec = {
                "job_id": job.id,
                "properties": compiled_props,
                "timeout_seconds": job.timeout_seconds,
            }

            result = await self.verifier.invoke(job_spec)

            # Parse result
            overall_result = VerificationResult(result.get("result", "error"))
            property_results = result.get("property_results", [])
            proof_data = result.get("proof_data", "")
            proof_hash = result.get("proof_hash", "")
            duration_ms = result.get("duration_ms") or 0

            if not proof_hash and proof_data:
                proof_hash = hashlib.sha3_256(proof_data.encode()).hexdigest()

            # v1.2.4 repricing: apply heavy-tail solver-time surcharge to
            # the quoted cost now that we know how long Z3 actually took.
            # ``job.cost`` was set to the minimum (base + per-property) at
            # submit time; we add the surcharge and persist the updated
            # value before marking the job completed.
            surcharge = _compute_solver_surcharge(int(duration_ms))
            if surcharge > 0:
                job.cost = job.cost + surcharge
                await self.storage.update_job_cost(job.id, job.cost)

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
            logger.exception("Verification job %s failed", job.id)
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
