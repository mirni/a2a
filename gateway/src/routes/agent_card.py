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
    },
    {
        "id": "payments",
        "name": "Payments & Escrow",
        "description": "Payment intents (authorize/capture), standard and performance-gated escrow, subscriptions, split payments, and refunds",
    },
    {
        "id": "identity",
        "name": "Identity & Reputation",
        "description": "Ed25519 cryptographic agent identity, verifiable claims, metric commitments, organizations, and reputation scoring",
    },
    {
        "id": "marketplace",
        "name": "Service Marketplace",
        "description": "Service registration, discovery, matching, ratings, and strategy comparison",
    },
    {
        "id": "trust",
        "name": "Trust Scoring",
        "description": "Composite trust scores, SLA compliance checking, and server search",
    },
    {
        "id": "messaging",
        "name": "Agent Messaging",
        "description": "End-to-end encrypted agent-to-agent messaging and price negotiation",
    },
    {
        "id": "disputes",
        "name": "Dispute Resolution",
        "description": "Dispute lifecycle management: open, respond, resolve, with 7-day response deadline",
    },
    {
        "id": "infrastructure",
        "name": "Infrastructure",
        "description": "API key management, webhook registration with HMAC-signed delivery, event bus with schema registry, audit logging, and database operations",
    },
]


@router.get("/.well-known/agent-card.json", include_in_schema=False)
async def agent_card(request: Request) -> JSONResponse:
    """Return A2A protocol agent card for service discovery."""
    base_url = os.environ.get("A2A_BASE_URL", str(request.base_url).rstrip("/"))

    card = {
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
            }
            for svc in _SERVICES
        ],
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
    }

    return JSONResponse(card)
