"""Pydantic models for the Formal Gatekeeper verification system.

Covers verification jobs, property specifications, proof artifacts,
and related enums for the Z3 SMT-based verification pipeline.

All timestamps are Unix floats (time.time()).
All monetary values use Decimal (never float).
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class VerificationStatus(StrEnum):
    """Lifecycle states for a verification job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class VerificationResult(StrEnum):
    """Possible outcomes of a verification job."""

    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"
    ERROR = "error"


class VerificationScope(StrEnum):
    """Domain scope of the verification properties."""

    ECONOMIC = "economic"
    WORKFLOW = "workflow"
    NETWORK = "network"
    CONTRACT = "contract"


class PropertySpec(BaseModel):
    """Specification of a single Z3 property to verify."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "balance_conservation",
                    "scope": "economic",
                    "language": "z3_smt2",
                    "expression": "(declare-const x Int)\n(declare-const y Int)\n(assert (>= x 0))\n(assert (>= y 0))\n(assert (= (+ x y) 100))",
                    "description": "Verify that balances sum to total supply",
                }
            ]
        },
    )

    name: str
    scope: VerificationScope = VerificationScope.ECONOMIC
    language: str = "z3_smt2"  # Only z3_smt2 for Phase 1
    expression: str
    description: str = ""


class VerificationJob(BaseModel):
    """A verification job submitted by an agent."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "id": "vj-abc12345",
                    "agent_id": "agent-alice",
                    "scope": "economic",
                    "status": "pending",
                    "properties": [
                        {
                            "name": "balance_conservation",
                            "scope": "economic",
                            "language": "z3_smt2",
                            "expression": "(declare-const x Int)\n(assert (> x 0))",
                            "description": "Check positive balance",
                        }
                    ],
                    "timeout_seconds": 300,
                    "result": None,
                    "proof_artifact_id": None,
                    "webhook_url": None,
                    "idempotency_key": None,
                    "cost": "5.0",
                    "metadata": {},
                    "created_at": 1711612800.0,
                    "updated_at": 1711612800.0,
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: f"vj-{uuid.uuid4().hex[:12]}")
    agent_id: str
    scope: VerificationScope = VerificationScope.ECONOMIC
    status: VerificationStatus = VerificationStatus.PENDING
    properties: list[PropertySpec]
    timeout_seconds: int = Field(default=300, ge=10, le=900)
    result: VerificationResult | None = None
    proof_artifact_id: str | None = None
    webhook_url: str | None = None
    idempotency_key: str | None = None
    cost: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    @field_serializer("cost")
    @classmethod
    def _serialize_cost(cls, v: Decimal) -> str:
        return str(v)


class ProofArtifact(BaseModel):
    """Cryptographic proof artifact from a completed verification."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "id": "pf-abc12345",
                    "job_id": "vj-abc12345",
                    "agent_id": "agent-alice",
                    "result": "satisfied",
                    "proof_hash": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
                    "proof_data": "eyJqb2JfaWQiOiAidmotYWJjMTIzNDUiLCAicmVzdWx0IjogInNhdGlzZmllZCJ9",
                    "signature": "sig_hex_string",
                    "signer_public_key": "pub_hex_string",
                    "counterexample": None,
                    "property_results": [],
                    "valid_until": 1714204800.0,
                    "created_at": 1711612800.0,
                }
            ]
        },
    )

    id: str = Field(default_factory=lambda: f"pf-{uuid.uuid4().hex[:12]}")
    job_id: str
    agent_id: str
    result: VerificationResult
    proof_hash: str  # SHA3-256 hex
    proof_data: str  # base64-encoded JSON
    signature: str = ""  # Ed25519 hex
    signer_public_key: str = ""
    counterexample: str | None = None
    property_results: list[dict[str, Any]] = Field(default_factory=list)
    valid_until: float = Field(default_factory=lambda: time.time() + 30 * 86400)  # 30 days
    created_at: float = Field(default_factory=time.time)
