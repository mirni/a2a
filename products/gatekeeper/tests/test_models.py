"""Tests for gatekeeper models — validation, serialization, schema examples."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from products.gatekeeper.src.models import (
    ProofArtifact,
    PropertySpec,
    VerificationJob,
    VerificationResult,
    VerificationScope,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# PropertySpec
# ---------------------------------------------------------------------------


class TestPropertySpec:
    def test_create_valid(self):
        p = PropertySpec(
            name="test_prop",
            expression="(declare-const x Int)\n(assert (> x 0))",
        )
        assert p.name == "test_prop"
        assert p.scope == VerificationScope.ECONOMIC
        assert p.language == "z3_smt2"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            PropertySpec(
                name="test",
                expression="(assert true)",
                unknown_field="bad",
            )

    def test_schema_example_valid(self):
        examples = PropertySpec.model_config["json_schema_extra"]["examples"]
        for ex in examples:
            p = PropertySpec(**ex)
            assert p.name == "balance_conservation"


# ---------------------------------------------------------------------------
# VerificationJob
# ---------------------------------------------------------------------------


class TestVerificationJob:
    def test_create_minimal(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[
                PropertySpec(name="p1", expression="(assert true)")
            ],
        )
        assert job.id.startswith("vj-")
        assert job.status == VerificationStatus.PENDING
        assert job.result is None
        assert job.cost == Decimal("0")
        assert job.scope == VerificationScope.ECONOMIC

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            VerificationJob(
                agent_id="agent-test",
                properties=[],
                extra_field="bad",
            )

    def test_timeout_validation(self):
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[],
                timeout_seconds=5,  # Below minimum of 10
            )
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[],
                timeout_seconds=1000,  # Above maximum of 900
            )

    def test_cost_serialization(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[],
            cost=Decimal("5.5"),
        )
        data = job.model_dump()
        assert data["cost"] == "5.5"

    def test_schema_example_valid(self):
        examples = VerificationJob.model_config["json_schema_extra"]["examples"]
        for ex in examples:
            job = VerificationJob(**ex)
            assert job.agent_id == "agent-alice"

    def test_all_statuses(self):
        for status in VerificationStatus:
            assert status.value in (
                "pending", "running", "completed", "failed", "timeout", "cancelled"
            )

    def test_all_results(self):
        for result in VerificationResult:
            assert result.value in ("satisfied", "violated", "unknown", "error")

    def test_all_scopes(self):
        for scope in VerificationScope:
            assert scope.value in ("economic", "workflow", "network", "contract")


# ---------------------------------------------------------------------------
# ProofArtifact
# ---------------------------------------------------------------------------


class TestProofArtifact:
    def test_create_valid(self):
        proof = ProofArtifact(
            job_id="vj-test",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="abc123",
            proof_data="eyJkYXRhIjogInRlc3QifQ==",
        )
        assert proof.id.startswith("pf-")
        assert proof.result == VerificationResult.SATISFIED

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ProofArtifact(
                job_id="vj-test",
                agent_id="agent-test",
                result=VerificationResult.SATISFIED,
                proof_hash="abc",
                proof_data="data",
                bogus="nope",
            )

    def test_schema_example_valid(self):
        examples = ProofArtifact.model_config["json_schema_extra"]["examples"]
        for ex in examples:
            proof = ProofArtifact(**ex)
            assert proof.job_id == "vj-abc12345"

    def test_default_validity(self):
        import time

        proof = ProofArtifact(
            job_id="vj-test",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="abc",
            proof_data="data",
        )
        # Valid for ~30 days
        assert proof.valid_until > time.time() + 29 * 86400
