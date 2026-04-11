"""Response models for the A2A SDK.

Infrastructure models (ExecuteResponse, ToolPricing, HealthResponse) remain as
dataclasses for backward compatibility.

Tool-specific response models use Pydantic v2 with:
- extra = "forbid" on all request/response models
- json_schema_extra examples for documentation
- Decimal for all currency-related fields
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

# ===========================================================================
# Infrastructure dataclass models (unchanged wire-format)
# ===========================================================================


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


# ===========================================================================
# Pydantic base for typed tool responses
# ===========================================================================


class _ToolResponse(BaseModel):
    """Base class for all typed tool response models.

    Uses ``extra="ignore"`` so that REST endpoints returning additional
    fields (e.g. ``currency``, ``metadata``) don't cause validation errors.
    """

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_dict(cls, data: dict[str, Any]):  # noqa: ANN206
        return cls.model_validate(data)


# ===========================================================================
# Billing tool responses
# ===========================================================================


class BalanceResponse(_ToolResponse):
    """Response from get_balance tool."""

    balance: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"balance": "100.00"}]},
    )


class DepositResponse(_ToolResponse):
    """Response from deposit tool."""

    new_balance: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"new_balance": "200.00"}]},
    )


# ===========================================================================
# Payment tool responses
# ===========================================================================


class PaymentIntentResponse(_ToolResponse):
    """Response from create_intent / capture_intent tools."""

    id: str
    status: str
    amount: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "intent_abc123", "status": "pending", "amount": "10.00"}]},
    )


class EscrowResponse(_ToolResponse):
    """Response from create_escrow / release_escrow tools."""

    id: str
    status: str
    amount: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "escrow_abc123", "status": "held", "amount": "50.00"}]},
    )


class CancelEscrowResponse(_ToolResponse):
    """Response from cancel_escrow tool."""

    id: str
    status: str
    amount: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "escrow_abc123", "status": "cancelled", "amount": "50.00"}]},
    )


class VoidPaymentResponse(_ToolResponse):
    """Response from refund_intent (void_payment) tool."""

    id: str
    status: str
    amount: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "intent_abc123", "status": "refunded", "amount": "10.00"}]},
    )


class RefundSettlementResponse(_ToolResponse):
    """Response from refund_settlement tool."""

    id: str
    settlement_id: str
    amount: Decimal
    status: str
    reason: str | None = None

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "refund_abc123",
                    "settlement_id": "settle_abc123",
                    "amount": "5.00",
                    "status": "refunded",
                    "reason": "service not delivered",
                }
            ]
        },
    )


# ===========================================================================
# Subscription tool responses
# ===========================================================================


class SubscriptionResponse(_ToolResponse):
    """Response from create_subscription tool."""

    id: str
    status: str
    amount: Decimal
    interval: str
    next_charge_at: float

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "sub_abc123",
                    "status": "active",
                    "amount": "10.00",
                    "interval": "daily",
                    "next_charge_at": 1700000000.0,
                }
            ]
        },
    )


class CancelSubscriptionResponse(_ToolResponse):
    """Response from cancel_subscription tool."""

    id: str
    status: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "sub_abc123", "status": "cancelled"}]},
    )


class GetSubscriptionResponse(_ToolResponse):
    """Response from get_subscription tool."""

    id: str
    payer: str
    payee: str
    amount: Decimal
    interval: str
    status: str
    next_charge_at: float
    charge_count: int
    created_at: float

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "sub_abc123",
                    "payer": "agent-a",
                    "payee": "agent-b",
                    "amount": "10.00",
                    "interval": "daily",
                    "status": "active",
                    "next_charge_at": 1700000000.0,
                    "charge_count": 5,
                    "created_at": 1699900000.0,
                }
            ]
        },
    )


class ListSubscriptionsResponse(_ToolResponse):
    """Response from list_subscriptions tool."""

    subscriptions: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"subscriptions": []}]},
    )


# ===========================================================================
# Marketplace tool responses
# ===========================================================================


class RegisterServiceResponse(_ToolResponse):
    """Response from register_service tool."""

    id: str
    name: str
    status: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"id": "svc_abc123", "name": "MyService", "status": "active"}]},
    )


class SearchServicesResponse(_ToolResponse):
    """Response from search_services tool."""

    services: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"services": [{"id": "svc_abc123", "name": "MyService"}]}]},
    )


class GetServiceResponse(_ToolResponse):
    """Response from get_service tool."""

    id: str
    name: str
    description: str
    category: str
    status: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "svc_abc123",
                    "name": "MyService",
                    "description": "A service",
                    "category": "ai",
                    "status": "active",
                }
            ]
        },
    )


class RateServiceResponse(_ToolResponse):
    """Response from rate_service tool."""

    service_id: str
    agent_id: str
    rating: int

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"service_id": "svc_abc123", "agent_id": "agent-a", "rating": 5}]},
    )


class ServiceMatch(_ToolResponse):
    """A single service match result."""

    service: dict[str, Any]
    rank_score: float
    match_reasons: list[str] = []

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [{"service": {"id": "svc1"}, "rank_score": 0.95, "match_reasons": ["keyword_match"]}]
        },
    )


# ===========================================================================
# Trust tool responses
# ===========================================================================


class TrustScoreResponse(_ToolResponse):
    """Response from get_trust_score tool."""

    server_id: str
    composite_score: float
    reliability_score: float
    security_score: float
    documentation_score: float = 0.0
    responsiveness_score: float = 0.0
    confidence: float
    window: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "server_id": "srv_abc123",
                    "composite_score": 0.92,
                    "reliability_score": 0.95,
                    "security_score": 0.88,
                    "documentation_score": 0.80,
                    "responsiveness_score": 0.90,
                    "confidence": 0.95,
                    "window": "24h",
                }
            ]
        },
    )


class SearchServersResponse(_ToolResponse):
    """Response from search_servers tool."""

    servers: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"servers": [{"id": "srv1", "name": "Server1"}]}]},
    )


# ===========================================================================
# Identity tool responses
# ===========================================================================


class RegisterAgentResponse(_ToolResponse):
    """Response from register_agent tool."""

    agent_id: str
    public_key: str
    created_at: float

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [{"agent_id": "agent-a", "public_key": "ed25519_hex...", "created_at": 1700000000.0}]
        },
    )


class GetAgentIdentityResponse(_ToolResponse):
    """Response from get_agent_identity tool."""

    agent_id: str
    public_key: str | None = None
    created_at: float | None = None
    org_id: str | None = None
    found: bool = True

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-a",
                    "public_key": "ed25519_hex...",
                    "created_at": 1700000000.0,
                    "org_id": None,
                    "found": True,
                }
            ]
        },
    )


class VerifyAgentResponse(_ToolResponse):
    """Response from verify_agent tool."""

    valid: bool

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"valid": True}]},
    )


class SubmitMetricsResponse(_ToolResponse):
    """Response from submit_metrics tool."""

    agent_id: str
    commitment_hashes: list[str]
    verified_at: float
    valid_until: float
    data_source: str
    signature: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "agent-a",
                    "commitment_hashes": ["abc123"],
                    "verified_at": 1700000000.0,
                    "valid_until": 1700100000.0,
                    "data_source": "self_reported",
                    "signature": "sig_hex...",
                }
            ]
        },
    )


class GetVerifiedClaimsResponse(_ToolResponse):
    """Response from get_verified_claims tool."""

    claims: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"claims": []}]},
    )


# ===========================================================================
# Messaging tool responses
# ===========================================================================


class SendMessageResponse(_ToolResponse):
    """Response from send_message tool."""

    id: str
    sender: str
    recipient: str
    thread_id: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {"id": "msg_abc123", "sender": "agent-a", "recipient": "agent-b", "thread_id": "thread_abc123"}
            ]
        },
    )


class GetMessagesResponse(_ToolResponse):
    """Response from get_messages tool."""

    messages: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"messages": []}]},
    )


class NegotiatePriceResponse(_ToolResponse):
    """Response from negotiate_price tool."""

    negotiation_id: str
    thread_id: str
    status: str
    proposed_amount: Decimal

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "negotiation_id": "neg_abc123",
                    "thread_id": "thread_abc123",
                    "status": "pending",
                    "proposed_amount": "50.00",
                }
            ]
        },
    )


# ===========================================================================
# Webhook tool responses
# ===========================================================================


class RegisterWebhookResponse(_ToolResponse):
    """Response from register_webhook tool."""

    id: str
    agent_id: str
    url: str
    event_types: list[str]
    filter_agent_ids: list[str] | None = None
    created_at: float
    active: bool

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [
                {
                    "id": "wh_abc123",
                    "agent_id": "agent-a",
                    "url": "https://hook.example.com",
                    "event_types": ["billing.deposit"],
                    "filter_agent_ids": None,
                    "created_at": 1700000000.0,
                    "active": True,
                }
            ]
        },
    )


class ListWebhooksResponse(_ToolResponse):
    """Response from list_webhooks tool."""

    webhooks: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"webhooks": []}]},
    )


class DeleteWebhookResponse(_ToolResponse):
    """Response from delete_webhook tool."""

    deleted: bool

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"deleted": True}]},
    )


# ===========================================================================
# API key tool responses
# ===========================================================================


class CreateApiKeyResponse(_ToolResponse):
    """Response from create_api_key tool."""

    key: str
    agent_id: str
    tier: str
    created_at: float

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [{"key": "a2a_free_abc123", "agent_id": "agent-a", "tier": "free", "created_at": 1700000000.0}]
        },
    )


class RotateKeyResponse(_ToolResponse):
    """Response from rotate_key tool."""

    new_key: str
    tier: str
    agent_id: str
    revoked: bool

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [{"new_key": "a2a_free_new123", "tier": "free", "agent_id": "agent-a", "revoked": True}]
        },
    )


# ===========================================================================
# Event tool responses
# ===========================================================================


class PublishEventResponse(_ToolResponse):
    """Response from publish_event tool."""

    event_id: int

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"event_id": 42}]},
    )


class GetEventsResponse(_ToolResponse):
    """Response from get_events tool."""

    events: list[dict[str, Any]]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"events": []}]},
    )


# ===========================================================================
# Org tool responses
# ===========================================================================


class CreateOrgResponse(_ToolResponse):
    """Response from create_org tool."""

    org_id: str
    name: str
    created_at: float

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"org_id": "org_abc123", "name": "MyOrg", "created_at": 1700000000.0}]},
    )


class GetOrgResponse(_ToolResponse):
    """Response from get_org tool."""

    org_id: str
    name: str
    created_at: float
    members: list[Any]

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "examples": [{"org_id": "org_abc123", "name": "MyOrg", "created_at": 1700000000.0, "members": []}]
        },
    )


class AddAgentToOrgResponse(_ToolResponse):
    """Response from add_agent_to_org tool."""

    agent_id: str
    org_id: str

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"examples": [{"agent_id": "agent-a", "org_id": "org_abc123"}]},
    )


# ===========================================================================
# Gatekeeper (formal verifier) tool responses
# ===========================================================================


class _GatekeeperResponse(_ToolResponse):
    """Base for gatekeeper responses that echoes the raw dict on demand.

    Gatekeeper responses carry many optional fields (proof_hash,
    property_results, counterexample, …) that only show up for certain
    outcomes. Rather than enumerating every combination we keep the
    minimal typed surface and expose the full payload via ``to_raw_dict``
    so helpers like :func:`sdk.src.a2a_client.verifier.prove_policy` can
    fold the details into a :class:`ProofResult`.
    """

    model_config = ConfigDict(extra="allow")

    def to_raw_dict(self) -> dict[str, Any]:
        """Return the full payload as a plain dict."""
        return self.model_dump()


class SubmitVerificationResponse(_GatekeeperResponse):
    """Response from POST /v1/gatekeeper/jobs."""

    job_id: str
    status: str
    agent_id: str | None = None
    cost: str | Decimal | float | None = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "job_id": "vj-abc123",
                    "status": "completed",
                    "agent_id": "agent-alice",
                    "cost": "12",
                    "result": "satisfied",
                }
            ]
        },
    )


class VerificationJobResponse(_GatekeeperResponse):
    """Response from GET /v1/gatekeeper/jobs/{job_id}."""

    job_id: str
    status: str
    agent_id: str | None = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "job_id": "vj-abc123",
                    "status": "completed",
                    "agent_id": "agent-alice",
                    "result": "satisfied",
                }
            ]
        },
    )


class VerifyProofResponse(_GatekeeperResponse):
    """Response from POST /v1/gatekeeper/proofs/verify."""

    valid: bool
    reason: str | None = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {"valid": True, "proof_id": "pf-abc123", "result": "satisfied"},
                {"valid": False, "reason": "proof_expired"},
            ]
        },
    )
