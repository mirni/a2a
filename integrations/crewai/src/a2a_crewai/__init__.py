"""A2A CrewAI integration — tool wrappers for the A2A Commerce Platform."""

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

__all__ = [
    # Schemas
    "GetBalanceInput",
    "DepositInput",
    "CreatePaymentIntentInput",
    "CapturePaymentInput",
    "CreateEscrowInput",
    "ReleaseEscrowInput",
    "SearchServicesInput",
    "GetTrustScoreInput",
    "RegisterAgentInput",
    "SendMessageInput",
    # Base (lazy)
    "A2ACrewTool",
    "create_tool",
    # Tools (lazy)
    "A2AGetBalance",
    "A2ADeposit",
    "A2ACreatePaymentIntent",
    "A2ACapturePayment",
    "A2ACreateEscrow",
    "A2AReleaseEscrow",
    "A2ASearchServices",
    "A2AGetTrustScore",
    "A2ARegisterAgent",
    "A2ASendMessage",
    # Toolkit (lazy)
    "A2AToolkit",
]


def __getattr__(name: str):
    """Lazy imports for base, tools, and toolkit modules."""
    if name in ("A2ACrewTool", "create_tool"):
        from a2a_crewai._base import A2ACrewTool, create_tool

        return {"A2ACrewTool": A2ACrewTool, "create_tool": create_tool}[name]
    if name in (
        "A2AGetBalance",
        "A2ADeposit",
        "A2ACreatePaymentIntent",
        "A2ACapturePayment",
        "A2ACreateEscrow",
        "A2AReleaseEscrow",
        "A2ASearchServices",
        "A2AGetTrustScore",
        "A2ARegisterAgent",
        "A2ASendMessage",
    ):
        from a2a_crewai import tools as _tools

        return getattr(_tools, name)
    if name == "A2AToolkit":
        from a2a_crewai.toolkit import A2AToolkit

        return A2AToolkit
    raise AttributeError(f"module 'a2a_crewai' has no attribute {name!r}")
