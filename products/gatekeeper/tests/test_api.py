"""Tests for GatekeeperAPI — job lifecycle with mocked verifier backend."""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest

from products.gatekeeper.src.api import (
    GatekeeperAPI,
    IdempotencyConflictError,
    JobAlreadyTerminalError,
    JobNotFoundError,
    ProofNotFoundError,
)
from products.gatekeeper.src.models import (
    VerificationResult,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Mock verifier backend
# ---------------------------------------------------------------------------


def _make_satisfied_response(job_id: str = "vj-test") -> dict[str, Any]:
    """Create a mock Lambda response indicating SAT."""
    proof_blob = json.dumps(
        {
            "job_id": job_id,
            "result": "satisfied",
            "property_results": [{"name": "p1", "result": "satisfied", "model": "[x = 5]"}],
        },
        sort_keys=True,
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "result": "satisfied",
        "property_results": [{"name": "p1", "result": "satisfied", "model": "[x = 5]"}],
        "proof_data": proof_blob,
        "proof_hash": hashlib.sha3_256(proof_blob.encode()).hexdigest(),
        "duration_ms": 42,
    }


def _make_violated_response(job_id: str = "vj-test") -> dict[str, Any]:
    """Create a mock Lambda response indicating UNSAT."""
    proof_blob = json.dumps(
        {
            "job_id": job_id,
            "result": "violated",
            "property_results": [{"name": "p1", "result": "violated", "reason": "unsatisfiable"}],
        },
        sort_keys=True,
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "result": "violated",
        "property_results": [{"name": "p1", "result": "violated", "reason": "unsatisfiable"}],
        "proof_data": proof_blob,
        "proof_hash": hashlib.sha3_256(proof_blob.encode()).hexdigest(),
        "duration_ms": 42,
    }


def _make_response_without_hash(job_id: str = "vj-test") -> dict[str, Any]:
    """Mock Lambda response with no proof_hash (tests fallback computation)."""
    proof_blob = json.dumps(
        {
            "job_id": job_id,
            "result": "satisfied",
            "property_results": [{"name": "p1", "result": "satisfied", "model": "[x = 1]"}],
        },
        sort_keys=True,
    )
    return {
        "job_id": job_id,
        "status": "completed",
        "result": "satisfied",
        "property_results": [{"name": "p1", "result": "satisfied", "model": "[x = 1]"}],
        "proof_data": proof_blob,
        # proof_hash intentionally omitted
        "duration_ms": 10,
    }


# ---------------------------------------------------------------------------
# Submit Verification
# ---------------------------------------------------------------------------


class TestSubmitVerification:
    @pytest.mark.asyncio
    async def test_submit_without_verifier(self, api):
        """Job is created in PENDING state when no verifier is attached."""
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.PENDING
        assert job.cost == Decimal("6")  # 5 base + 1 per property
        assert len(job.properties) == 1

    @pytest.mark.asyncio
    async def test_submit_with_verifier_satisfied(self, storage):
        """Job completes immediately with verifier attached and SAT result."""
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_satisfied_response(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.COMPLETED
        assert job.result == VerificationResult.SATISFIED
        assert job.proof_artifact_id is not None

    @pytest.mark.asyncio
    async def test_submit_with_verifier_violated(self, storage):
        """Job completes with violated result."""
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_violated_response(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert false)"}],
        )
        assert job.status == VerificationStatus.COMPLETED
        assert job.result == VerificationResult.VIOLATED

    @pytest.mark.asyncio
    async def test_submit_with_verifier_error(self, storage):
        """Job fails when verifier raises an exception."""
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = RuntimeError("Lambda timeout")
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.FAILED
        assert job.result == VerificationResult.ERROR

    @pytest.mark.asyncio
    async def test_submit_with_verifier_no_proof_hash(self, storage):
        """Fallback hash computation when verifier omits proof_hash."""
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_response_without_hash(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.COMPLETED
        proof = await api.get_proof(job.proof_artifact_id)
        assert proof.proof_hash != ""  # Hash was computed by fallback

    @pytest.mark.asyncio
    async def test_submit_idempotency(self, api):
        """Second submit with same idempotency key returns first job."""
        job1 = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
            idempotency_key="idem-001",
        )
        job2 = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p2", "expression": "(assert false)"}],
            idempotency_key="idem-001",
        )
        assert job1.id == job2.id

    @pytest.mark.asyncio
    async def test_submit_idempotency_different_agent_raises(self, api):
        """Idempotency key from a different agent raises IdempotencyConflictError."""
        await api.submit_verification(
            agent_id="agent-alice",
            properties=[{"name": "p1", "expression": "(assert true)"}],
            idempotency_key="idem-conflict",
        )
        with pytest.raises(IdempotencyConflictError, match="different agent"):
            await api.submit_verification(
                agent_id="agent-bob",
                properties=[{"name": "p1", "expression": "(assert true)"}],
                idempotency_key="idem-conflict",
            )

    @pytest.mark.asyncio
    async def test_submit_cost_calculation(self, api):
        """Cost is 5 base + 1 per property."""
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": f"p{i}", "expression": "(assert true)"} for i in range(3)],
        )
        assert job.cost == Decimal("8")  # 5 + 3

    @pytest.mark.asyncio
    async def test_submit_with_metadata(self, api):
        """Metadata is stored."""
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
            metadata={"workflow": "escrow-release"},
        )
        assert job.metadata == {"workflow": "escrow-release"}

    @pytest.mark.asyncio
    async def test_submit_invalid_scope(self, api):
        """Invalid scope raises ValueError."""
        with pytest.raises(ValueError):
            await api.submit_verification(
                agent_id="agent-test",
                properties=[{"name": "p1", "expression": "(assert true)"}],
                scope="invalid",
            )


# ---------------------------------------------------------------------------
# Get Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_existing(self, api):
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        fetched = await api.get_verification_status(job.id)
        assert fetched.id == job.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, api):
        with pytest.raises(JobNotFoundError):
            await api.get_verification_status("vj-nope")


# ---------------------------------------------------------------------------
# List Jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    @pytest.mark.asyncio
    async def test_list_empty(self, api):
        jobs = await api.list_verification_jobs("agent-nobody")
        assert jobs == []

    @pytest.mark.asyncio
    async def test_list_with_results(self, api):
        for _ in range(3):
            await api.submit_verification(
                agent_id="agent-lister",
                properties=[{"name": "p", "expression": "(assert true)"}],
            )
        jobs = await api.list_verification_jobs("agent-lister")
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_with_status_filter(self, api):
        await api.submit_verification(
            agent_id="agent-filter",
            properties=[{"name": "p", "expression": "(assert true)"}],
        )
        jobs = await api.list_verification_jobs("agent-filter", status="pending")
        assert len(jobs) == 1
        jobs = await api.list_verification_jobs("agent-filter", status="completed")
        assert len(jobs) == 0


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_pending(self, api):
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        cancelled = await api.cancel_verification(job.id)
        assert cancelled.status == VerificationStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent(self, api):
        with pytest.raises(JobNotFoundError):
            await api.cancel_verification("vj-nope")

    @pytest.mark.asyncio
    async def test_cancel_completed_fails(self, storage):
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_satisfied_response(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.COMPLETED
        with pytest.raises(JobAlreadyTerminalError):
            await api.cancel_verification(job.id)

    @pytest.mark.asyncio
    async def test_cancel_failed_raises(self, storage):
        """Failed jobs are terminal and cannot be cancelled."""
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = RuntimeError("boom")
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        assert job.status == VerificationStatus.FAILED
        with pytest.raises(JobAlreadyTerminalError):
            await api.cancel_verification(job.id)

    @pytest.mark.asyncio
    async def test_cancel_timeout_raises(self, storage):
        """Timed-out jobs are terminal and cannot be cancelled."""
        api = GatekeeperAPI(storage=storage)
        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        # Manually transition to TIMEOUT
        await storage.update_job_status(job.id, VerificationStatus.TIMEOUT)
        with pytest.raises(JobAlreadyTerminalError):
            await api.cancel_verification(job.id)


# ---------------------------------------------------------------------------
# Proofs
# ---------------------------------------------------------------------------


class TestProofs:
    @pytest.mark.asyncio
    async def test_get_proof(self, storage):
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_satisfied_response(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        proof = await api.get_proof(job.proof_artifact_id)
        assert proof.job_id == job.id
        assert proof.result == VerificationResult.SATISFIED

    @pytest.mark.asyncio
    async def test_get_proof_not_found(self, api):
        with pytest.raises(ProofNotFoundError):
            await api.get_proof("pf-nonexistent")

    @pytest.mark.asyncio
    async def test_verify_proof_valid(self, storage):
        mock_verifier = AsyncMock()
        mock_verifier.invoke.side_effect = lambda spec: _make_satisfied_response(spec["job_id"])
        api = GatekeeperAPI(storage=storage, verifier=mock_verifier)

        job = await api.submit_verification(
            agent_id="agent-test",
            properties=[{"name": "p1", "expression": "(assert true)"}],
        )
        proof = await api.get_proof(job.proof_artifact_id)

        result = await api.verify_proof(proof.proof_hash)
        assert result["valid"] is True
        assert result["proof_id"] == proof.id

    @pytest.mark.asyncio
    async def test_verify_proof_not_found(self, api):
        result = await api.verify_proof("nonexistent-hash")
        assert result["valid"] is False
        assert result["reason"] == "proof_not_found"

    @pytest.mark.asyncio
    async def test_verify_proof_expired(self, storage):
        """Manually insert an expired proof and verify it."""
        from products.gatekeeper.src.models import ProofArtifact

        proof = ProofArtifact(
            job_id="vj-expired",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="expired-hash",
            proof_data="data",
            valid_until=time.time() - 1,  # Already expired
        )
        await storage.create_proof(proof)

        api = GatekeeperAPI(storage=storage)
        result = await api.verify_proof("expired-hash")
        assert result["valid"] is False
        assert result["reason"] == "proof_expired"

    @pytest.mark.asyncio
    async def test_verify_proof_hash_mismatch(self, storage):
        """Proof with corrupted data returns hash_mismatch."""
        from products.gatekeeper.src.models import ProofArtifact

        proof = ProofArtifact(
            job_id="vj-corrupt",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="definitely-wrong-hash",
            proof_data="some data that does not match the hash",
            valid_until=time.time() + 86400,
        )
        await storage.create_proof(proof)

        api = GatekeeperAPI(storage=storage)
        result = await api.verify_proof("definitely-wrong-hash")
        assert result["valid"] is False
        assert result["reason"] == "hash_mismatch"


# ---------------------------------------------------------------------------
# from_env
# ---------------------------------------------------------------------------


class TestFromEnv:
    @pytest.mark.asyncio
    async def test_from_env_defaults(self, storage, monkeypatch):
        """from_env reads signing/public keys from environment."""
        monkeypatch.setenv("VERIFIER_SIGNING_KEY", "sk-test-123")
        monkeypatch.setenv("VERIFIER_PUBLIC_KEY", "pk-test-456")
        api = GatekeeperAPI.from_env(storage)
        assert api.signing_key == "sk-test-123"
        assert api.public_key == "pk-test-456"
        assert api.storage is storage

    @pytest.mark.asyncio
    async def test_from_env_missing_keys(self, storage, monkeypatch):
        """from_env defaults to empty strings when env vars not set."""
        monkeypatch.delenv("VERIFIER_SIGNING_KEY", raising=False)
        monkeypatch.delenv("VERIFIER_PUBLIC_KEY", raising=False)
        api = GatekeeperAPI.from_env(storage)
        assert api.signing_key == ""
        assert api.public_key == ""


# ---------------------------------------------------------------------------
# _extract_counterexample
# ---------------------------------------------------------------------------


class TestExtractCounterexample:
    def test_violated_with_reason(self):
        results = [{"name": "p1", "result": "violated", "reason": "unsatisfiable"}]
        assert GatekeeperAPI._extract_counterexample(results) == "unsatisfiable"

    def test_satisfied_with_model(self):
        results = [{"name": "p1", "result": "satisfied", "model": "[x = 5]"}]
        assert GatekeeperAPI._extract_counterexample(results) == "[x = 5]"

    def test_empty_results(self):
        assert GatekeeperAPI._extract_counterexample([]) is None

    def test_no_matching_fields(self):
        results = [{"name": "p1", "result": "unknown"}]
        assert GatekeeperAPI._extract_counterexample(results) is None
