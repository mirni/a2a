"""Tests for GatekeeperStorage — CRUD operations on verification jobs and proofs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from products.gatekeeper.src.models import (
    ProofArtifact,
    PropertySpec,
    VerificationJob,
    VerificationResult,
    VerificationStatus,
)


# ---------------------------------------------------------------------------
# Verification Jobs
# ---------------------------------------------------------------------------


class TestJobCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get_job(self, storage):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(name="p1", expression="(assert true)")],
            cost=Decimal("6"),
        )
        created = await storage.create_job(job)
        assert created.id == job.id

        fetched = await storage.get_job(job.id)
        assert fetched is not None
        assert fetched.agent_id == "agent-test"
        assert fetched.status == VerificationStatus.PENDING
        assert fetched.cost == Decimal("6")
        assert len(fetched.properties) == 1
        assert fetched.properties[0].name == "p1"

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, storage):
        result = await storage.get_job("vj-nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_idempotency_key_lookup(self, storage):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(name="p1", expression="(assert true)")],
            idempotency_key="idem-123",
        )
        await storage.create_job(job)

        found = await storage.get_job_by_idempotency_key("idem-123")
        assert found is not None
        assert found.id == job.id

        not_found = await storage.get_job_by_idempotency_key("idem-999")
        assert not_found is None

    @pytest.mark.asyncio
    async def test_update_job_status(self, storage):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[],
        )
        await storage.create_job(job)

        updated = await storage.update_job_status(
            job.id, VerificationStatus.RUNNING
        )
        assert updated.status == VerificationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_job_with_result(self, storage):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[],
        )
        await storage.create_job(job)

        updated = await storage.update_job_status(
            job.id,
            VerificationStatus.COMPLETED,
            result=VerificationResult.SATISFIED,
            proof_artifact_id="pf-123",
        )
        assert updated.status == VerificationStatus.COMPLETED
        assert updated.result == VerificationResult.SATISFIED
        assert updated.proof_artifact_id == "pf-123"

    @pytest.mark.asyncio
    async def test_list_jobs(self, storage):
        for i in range(5):
            job = VerificationJob(
                agent_id="agent-list",
                properties=[],
            )
            await storage.create_job(job)

        jobs = await storage.list_jobs("agent-list")
        assert len(jobs) == 5

    @pytest.mark.asyncio
    async def test_list_jobs_filter_status(self, storage):
        job1 = VerificationJob(agent_id="agent-filter", properties=[])
        job2 = VerificationJob(agent_id="agent-filter", properties=[])
        await storage.create_job(job1)
        await storage.create_job(job2)
        await storage.update_job_status(job2.id, VerificationStatus.RUNNING)

        pending = await storage.list_jobs("agent-filter", status="pending")
        assert len(pending) == 1
        assert pending[0].id == job1.id

    @pytest.mark.asyncio
    async def test_list_jobs_limit(self, storage):
        for _ in range(10):
            await storage.create_job(
                VerificationJob(agent_id="agent-limit", properties=[])
            )

        jobs = await storage.list_jobs("agent-limit", limit=3)
        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_jobs_different_agent(self, storage):
        await storage.create_job(
            VerificationJob(agent_id="agent-a", properties=[])
        )
        await storage.create_job(
            VerificationJob(agent_id="agent-b", properties=[])
        )

        jobs_a = await storage.list_jobs("agent-a")
        assert len(jobs_a) == 1


# ---------------------------------------------------------------------------
# Proof Artifacts
# ---------------------------------------------------------------------------


class TestProofCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get_proof(self, storage):
        proof = ProofArtifact(
            job_id="vj-test",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="hash123",
            proof_data="proof_data_blob",
        )
        created = await storage.create_proof(proof)
        assert created.id == proof.id

        fetched = await storage.get_proof(proof.id)
        assert fetched is not None
        assert fetched.proof_hash == "hash123"
        assert fetched.result == VerificationResult.SATISFIED

    @pytest.mark.asyncio
    async def test_get_nonexistent_proof(self, storage):
        result = await storage.get_proof("pf-nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_proof_by_job(self, storage):
        proof = ProofArtifact(
            job_id="vj-lookup",
            agent_id="agent-test",
            result=VerificationResult.VIOLATED,
            proof_hash="hash456",
            proof_data="data",
        )
        await storage.create_proof(proof)

        found = await storage.get_proof_by_job("vj-lookup")
        assert found is not None
        assert found.job_id == "vj-lookup"

    @pytest.mark.asyncio
    async def test_get_proof_by_hash(self, storage):
        proof = ProofArtifact(
            job_id="vj-hash",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="unique-hash-789",
            proof_data="data",
        )
        await storage.create_proof(proof)

        found = await storage.get_proof_by_hash("unique-hash-789")
        assert found is not None
        assert found.id == proof.id

        not_found = await storage.get_proof_by_hash("no-such-hash")
        assert not_found is None
