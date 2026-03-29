"""Data models for the A2A marketplace."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ServiceStatus(StrEnum):
    """Status of a service listing."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class PricingModelType(StrEnum):
    """Supported pricing models."""

    PER_CALL = "per_call"
    PER_TOKEN = "per_token"
    SUBSCRIPTION = "subscription"
    FREE = "free"


class SortBy(StrEnum):
    """Sort options for search results."""

    TRUST_SCORE = "trust_score"
    COST = "cost"
    CREATED_AT = "created_at"
    NAME = "name"


class MatchPreference(StrEnum):
    """Preference for best_match ranking."""

    COST = "cost"
    TRUST = "trust"
    LATENCY = "latency"


@dataclass(frozen=True)
class PricingModel:
    """Pricing configuration for a service."""

    model: PricingModelType
    cost: float = 0.0
    currency: str = "credits"

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model.value, "cost": self.cost, "currency": self.currency}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PricingModel:
        return cls(
            model=PricingModelType(d["model"]),
            cost=float(d.get("cost", 0.0)),
            currency=d.get("currency", "credits"),
        )


@dataclass(frozen=True)
class SLA:
    """Service level agreement definition."""

    uptime: float = 99.0  # percentage
    max_latency_ms: int = 1000

    def to_dict(self) -> dict[str, Any]:
        return {"uptime": self.uptime, "max_latency_ms": self.max_latency_ms}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SLA:
        return cls(
            uptime=float(d.get("uptime", 99.0)),
            max_latency_ms=int(d.get("max_latency_ms", 1000)),
        )


@dataclass
class ServiceCreate:
    """Input for registering a new service."""

    provider_id: str
    name: str
    description: str
    category: str
    tools: list[str] = field(default_factory=list)
    pricing: PricingModel = field(default_factory=lambda: PricingModel(model=PricingModelType.FREE))
    sla: SLA = field(default_factory=SLA)
    tags: list[str] = field(default_factory=list)
    endpoint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Service:
    """A registered service in the marketplace."""

    id: str
    provider_id: str
    name: str
    description: str
    category: str
    tools: list[str]
    pricing: PricingModel
    sla: SLA
    tags: list[str]
    status: ServiceStatus
    endpoint: str = ""
    trust_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ServiceSearchParams:
    """Parameters for searching the marketplace."""

    query: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    min_trust_score: float | None = None
    max_cost: float | None = None
    pricing_model: PricingModelType | None = None
    status: ServiceStatus = ServiceStatus.ACTIVE
    sort_by: SortBy = SortBy.TRUST_SCORE
    sort_desc: bool = True
    limit: int = 20
    offset: int = 0


@dataclass
class ServiceMatch:
    """Result from best_match with ranking score."""

    service: Service
    rank_score: float
    match_reasons: list[str] = field(default_factory=list)
