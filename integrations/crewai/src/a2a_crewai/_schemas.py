"""Pydantic input schemas for pre-built A2A CrewAI tools.

All schemas use ``extra="forbid"`` per project conventions.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class GetBalanceInput(BaseModel):
    """Input for get_balance tool."""

    agent_id: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"agent_id": "agent-1"}]},
    )


class DepositInput(BaseModel):
    """Input for deposit tool."""

    agent_id: str
    amount: Decimal

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"agent_id": "agent-1", "amount": "100.00"}]},
    )


class CreatePaymentIntentInput(BaseModel):
    """Input for create_intent tool."""

    payer: str
    payee: str
    amount: Decimal

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"payer": "agent-1", "payee": "agent-2", "amount": "25.00"}]},
    )


class CapturePaymentInput(BaseModel):
    """Input for capture_intent tool."""

    intent_id: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"intent_id": "intent-1"}]},
    )


class CreateEscrowInput(BaseModel):
    """Input for create_escrow tool."""

    payer: str
    payee: str
    amount: Decimal

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"payer": "agent-1", "payee": "agent-2", "amount": "50.00"}]},
    )


class ReleaseEscrowInput(BaseModel):
    """Input for release_escrow tool."""

    escrow_id: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"escrow_id": "escrow-1"}]},
    )


class SearchServicesInput(BaseModel):
    """Input for search_services tool."""

    query: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"query": "analytics"}]},
    )


class GetTrustScoreInput(BaseModel):
    """Input for get_trust_score tool."""

    server_id: str

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"server_id": "server-1"}]},
    )


class RegisterAgentInput(BaseModel):
    """Input for register_agent tool."""

    agent_id: str
    public_key: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"agent_id": "agent-1"}]},
    )


class SendMessageInput(BaseModel):
    """Input for send_message tool."""

    sender: str
    recipient: str
    message_type: str
    body: str
    subject: str | None = None
    thread_id: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "sender": "agent-1",
                    "recipient": "agent-2",
                    "message_type": "text",
                    "body": "Hello!",
                }
            ]
        },
    )
