"""Response models for the A2A SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecuteResponse:
    """Response from POST /execute."""

    success: bool
    result: dict[str, Any]
    charged: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecuteResponse:
        return cls(
            success=data["success"],
            result=data.get("result", {}),
            charged=data.get("charged", 0.0),
        )


@dataclass
class ToolPricing:
    """Pricing info for a single tool."""

    name: str
    service: str
    description: str
    pricing: dict[str, Any]
    tier_required: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    sla: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolPricing:
        return cls(
            name=data["name"],
            service=data["service"],
            description=data["description"],
            pricing=data.get("pricing", {}),
            tier_required=data.get("tier_required", "free"),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            sla=data.get("sla", {}),
        )


@dataclass
class HealthResponse:
    """Response from GET /health."""

    status: str
    version: str
    tools: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthResponse:
        return cls(
            status=data["status"],
            version=data["version"],
            tools=data["tools"],
        )


# ---------------------------------------------------------------------------
# Typed response models for specific tool results
# ---------------------------------------------------------------------------


@dataclass
class BalanceResponse:
    """Response from get_balance tool."""

    balance: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BalanceResponse:
        return cls(balance=data["balance"])


@dataclass
class DepositResponse:
    """Response from deposit tool."""

    new_balance: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DepositResponse:
        return cls(new_balance=data["new_balance"])


@dataclass
class PaymentIntentResponse:
    """Response from create_intent tool."""

    id: str
    status: str
    amount: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentIntentResponse:
        return cls(id=data["id"], status=data["status"], amount=data["amount"])


@dataclass
class EscrowResponse:
    """Response from create_escrow / release_escrow tools."""

    id: str
    status: str
    amount: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EscrowResponse:
        return cls(id=data["id"], status=data["status"], amount=data["amount"])


@dataclass
class TrustScoreResponse:
    """Response from get_trust_score tool."""

    server_id: str
    composite_score: float
    reliability_score: float
    security_score: float
    documentation_score: float
    responsiveness_score: float
    confidence: float
    window: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustScoreResponse:
        return cls(
            server_id=data["server_id"],
            composite_score=data["composite_score"],
            reliability_score=data["reliability_score"],
            security_score=data["security_score"],
            documentation_score=data.get("documentation_score", 0.0),
            responsiveness_score=data.get("responsiveness_score", 0.0),
            confidence=data["confidence"],
            window=data["window"],
        )


@dataclass
class ServiceMatch:
    """A single service match result."""

    service: dict[str, Any]
    rank_score: float
    match_reasons: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceMatch:
        return cls(
            service=data["service"],
            rank_score=data["rank_score"],
            match_reasons=data.get("match_reasons", []),
        )
