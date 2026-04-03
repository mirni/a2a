"""Pre-built A2A tool classes for CrewAI.

Each tool wraps a specific A2A SDK operation with typed args_schema.
"""

from __future__ import annotations

from typing import Any

from a2a_crewai._base import A2ACrewTool
from a2a_crewai._schemas import (
    CapturePaymentInput,
    CreateEscrowInput,
    CreatePaymentIntentInput,
    DepositInput,
    GetBalanceInput,
    GetTrustScoreInput,
    RegisterAgentInput,
    ReleaseEscrowInput,
    SearchServicesInput,
    SendMessageInput,
)


class A2AGetBalance(A2ACrewTool):
    """Get wallet balance for an agent."""

    name: str = "get_balance"
    description: str = "Get wallet balance for an agent"
    args_schema: Any = GetBalanceInput
    tool_name: str = "get_balance"


class A2ADeposit(A2ACrewTool):
    """Deposit credits into agent wallet."""

    name: str = "deposit"
    description: str = "Deposit credits into agent wallet"
    args_schema: Any = DepositInput
    tool_name: str = "deposit"


class A2ACreatePaymentIntent(A2ACrewTool):
    """Create a payment intent."""

    name: str = "create_intent"
    description: str = "Create a payment intent between agents"
    args_schema: Any = CreatePaymentIntentInput
    tool_name: str = "create_intent"


class A2ACapturePayment(A2ACrewTool):
    """Capture (settle) a payment intent."""

    name: str = "capture_intent"
    description: str = "Capture and settle a payment intent"
    args_schema: Any = CapturePaymentInput
    tool_name: str = "capture_intent"


class A2ACreateEscrow(A2ACrewTool):
    """Create an escrow hold."""

    name: str = "create_escrow"
    description: str = "Create an escrow hold between agents"
    args_schema: Any = CreateEscrowInput
    tool_name: str = "create_escrow"


class A2AReleaseEscrow(A2ACrewTool):
    """Release an escrow hold."""

    name: str = "release_escrow"
    description: str = "Release an escrow hold"
    args_schema: Any = ReleaseEscrowInput
    tool_name: str = "release_escrow"


class A2ASearchServices(A2ACrewTool):
    """Search for services in the marketplace."""

    name: str = "search_services"
    description: str = "Search for services in the marketplace"
    args_schema: Any = SearchServicesInput
    tool_name: str = "search_services"


class A2AGetTrustScore(A2ACrewTool):
    """Get trust score for a server."""

    name: str = "get_trust_score"
    description: str = "Get composite trust score for a server"
    args_schema: Any = GetTrustScoreInput
    tool_name: str = "get_trust_score"


class A2ARegisterAgent(A2ACrewTool):
    """Register a new agent identity."""

    name: str = "register_agent"
    description: str = "Register a new agent with cryptographic identity"
    args_schema: Any = RegisterAgentInput
    tool_name: str = "register_agent"


class A2ASendMessage(A2ACrewTool):
    """Send an agent-to-agent message."""

    name: str = "send_message"
    description: str = "Send an encrypted message to another agent"
    args_schema: Any = SendMessageInput
    tool_name: str = "send_message"
