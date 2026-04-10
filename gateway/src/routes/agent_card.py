"""/.well-known/agent-card.json — A2A protocol agent discovery."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.src._version import __version__

router = APIRouter()

_SERVICES = [
    {
        "id": "billing",
        "name": "Billing & Wallets",
        "description": "Agent wallets, credit deposits/withdrawals, usage tracking, budget caps, volume discounts, currency exchange, and leaderboards",
        "tags": ["billing", "wallet", "credits", "usage", "budget", "commerce"],
    },
    {
        "id": "payments",
        "name": "Payments & Escrow",
        "description": "Payment intents (authorize/capture), standard and performance-gated escrow, subscriptions, split payments, and refunds",
        "tags": ["payments", "escrow", "subscriptions", "refunds", "commerce"],
    },
    {
        "id": "identity",
        "name": "Identity & Reputation",
        "description": "Ed25519 cryptographic agent identity, verifiable claims, metric commitments, organizations, and reputation scoring",
        "tags": ["identity", "reputation", "ed25519", "verification", "claims"],
    },
    {
        "id": "marketplace",
        "name": "Service Marketplace",
        "description": "Service registration, discovery, matching, ratings, and strategy comparison",
        "tags": ["marketplace", "discovery", "ratings", "services"],
    },
    {
        "id": "trust",
        "name": "Trust Scoring",
        "description": "Composite trust scores, SLA compliance checking, and server search",
        "tags": ["trust", "reputation", "sla", "scoring"],
    },
    {
        "id": "messaging",
        "name": "Agent Messaging",
        "description": "End-to-end encrypted agent-to-agent messaging and price negotiation",
        "tags": ["messaging", "encryption", "negotiation", "communication"],
    },
    {
        "id": "disputes",
        "name": "Dispute Resolution",
        "description": "Dispute lifecycle management: open, respond, resolve, with 7-day response deadline",
        "tags": ["disputes", "resolution", "arbitration"],
    },
    {
        "id": "infrastructure",
        "name": "Infrastructure",
        "description": "API key management, webhook registration with HMAC-signed delivery, event bus with schema registry, audit logging, and database operations",
        "tags": ["infrastructure", "webhooks", "events", "audit", "api-keys"],
    },
]


def _build_agent_card(request: Request) -> dict:
    """Build the agent card payload."""
    base_url = os.environ.get("A2A_BASE_URL", str(request.base_url).rstrip("/"))

    return {
        "name": "A2A Commerce Gateway",
        "description": "Agent-to-agent commerce infrastructure: billing, payments, escrow, marketplace, identity, messaging, and trust scoring",
        "url": base_url,
        "version": __version__,
        "provider": {
            "organization": "Green Helix",
            "url": "https://greenhelix.net",
        },
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["bearer"],
            "description": "API key via Authorization: Bearer a2a_{tier}_{key} header. Free tier available (500 credits, 100 req/hr).",
        },
        "skills": [
            {
                "id": svc["id"],
                "name": svc["name"],
                "description": svc["description"],
                "tags": svc["tags"],
            }
            for svc in _SERVICES
        ],
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
    }


@router.get("/.well-known/agent.json", include_in_schema=False)
async def agent_json(request: Request) -> JSONResponse:
    """Return A2A protocol agent card at the standard well-known path."""
    return JSONResponse(_build_agent_card(request))


@router.get("/.well-known/agent-card.json", include_in_schema=False)
async def agent_card(request: Request) -> JSONResponse:
    """Return A2A protocol agent card (legacy path)."""
    return JSONResponse(_build_agent_card(request))
