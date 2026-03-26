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
