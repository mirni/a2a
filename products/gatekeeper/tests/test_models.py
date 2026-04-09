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

_VALID_PROP = {"name": "p1", "expression": "(assert true)"}


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

    def test_all_scopes(self):
        for scope in VerificationScope:
            p = PropertySpec(name="p", expression="(assert true)", scope=scope)
            assert p.scope == scope

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

    def test_name_max_length(self):
        with pytest.raises(ValidationError, match="String should have at most 128"):
            PropertySpec(name="x" * 129, expression="(assert true)")

    def test_expression_max_length(self):
        with pytest.raises(ValidationError, match="String should have at most 1000000"):
            PropertySpec(name="p", expression="x" * 1_000_001)

    def test_description_max_length(self):
        with pytest.raises(ValidationError, match="String should have at most 1000"):
            PropertySpec(name="p", expression="(assert true)", description="x" * 1001)

    def test_invalid_scope(self):
        with pytest.raises(ValidationError):
            PropertySpec(name="p", expression="(assert true)", scope="bogus")


# ---------------------------------------------------------------------------
# VerificationJob
# ---------------------------------------------------------------------------


class TestVerificationJob:
    def test_create_minimal(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(**_VALID_PROP)],
        )
        assert job.id.startswith("vj-")
        assert len(job.id) == 35  # "vj-" + 32 hex chars
        assert job.status == VerificationStatus.PENDING
        assert job.result is None
        assert job.cost == Decimal("0")
        assert job.scope == VerificationScope.ECONOMIC

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                extra_field="bad",
            )

    def test_empty_properties_rejected(self):
        with pytest.raises(ValidationError, match="at least 1"):
            VerificationJob(agent_id="agent-test", properties=[])

    def test_too_many_properties_rejected(self):
        props = [PropertySpec(name=f"p{i}", expression="(assert true)") for i in range(101)]
        with pytest.raises(ValidationError, match="Maximum 100"):
            VerificationJob(agent_id="agent-test", properties=props)

    def test_timeout_validation(self):
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                timeout_seconds=5,  # Below minimum of 10
            )
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                timeout_seconds=1000,  # Above maximum of 900
            )

    def test_timeout_boundary_values(self):
        """Boundary values 10 and 900 should be accepted."""
        j1 = VerificationJob(agent_id="a", properties=[PropertySpec(**_VALID_PROP)], timeout_seconds=10)
        assert j1.timeout_seconds == 10
        j2 = VerificationJob(agent_id="a", properties=[PropertySpec(**_VALID_PROP)], timeout_seconds=900)
        assert j2.timeout_seconds == 900

    def test_cost_serialization(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(**_VALID_PROP)],
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
            assert status.value in ("pending", "running", "completed", "failed", "timeout", "cancelled")

    def test_all_results(self):
        for result in VerificationResult:
            assert result.value in ("satisfied", "violated", "unknown", "error")

    def test_all_scopes(self):
        for scope in VerificationScope:
            assert scope.value in ("economic", "workflow", "network", "contract")

    def test_webhook_url_must_be_https(self):
        with pytest.raises(ValidationError, match="HTTPS"):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                webhook_url="http://evil.example.com/hook",
            )

    def test_webhook_url_https_accepted(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(**_VALID_PROP)],
            webhook_url="https://example.com/hook",
        )
        assert job.webhook_url == "https://example.com/hook"

    def test_webhook_url_none_accepted(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(**_VALID_PROP)],
            webhook_url=None,
        )
        assert job.webhook_url is None

    def test_agent_id_max_length(self):
        with pytest.raises(ValidationError, match="at most 128"):
            VerificationJob(
                agent_id="x" * 129,
                properties=[PropertySpec(**_VALID_PROP)],
            )

    def test_json_round_trip(self):
        job = VerificationJob(
            agent_id="agent-test",
            properties=[PropertySpec(**_VALID_PROP)],
            cost=Decimal("6"),
            metadata={"key": "value"},
        )
        json_str = job.model_dump_json()
        restored = VerificationJob.model_validate_json(json_str)
        assert restored.id == job.id
        assert restored.cost == job.cost
        assert restored.metadata == {"key": "value"}

    def test_invalid_status_value(self):
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                status="invalid",
            )

    def test_invalid_scope_value(self):
        with pytest.raises(ValidationError):
            VerificationJob(
                agent_id="agent-test",
                properties=[PropertySpec(**_VALID_PROP)],
                scope="invalid",
            )


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
        assert len(proof.id) == 35  # "pf-" + 32 hex chars
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
            assert proof.job_id.startswith("vj-")

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

    def test_property_results_serialization(self):
        proof = ProofArtifact(
            job_id="vj-test",
            agent_id="agent-test",
            result=VerificationResult.SATISFIED,
            proof_hash="abc",
            proof_data="data",
            property_results=[{"name": "p1", "result": "satisfied", "model": "[x = 5]"}],
        )
        data = proof.model_dump()
        assert data["property_results"][0]["name"] == "p1"
