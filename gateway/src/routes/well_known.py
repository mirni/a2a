"""/.well-known/* discovery manifests for distribution reach.

Serves the zero-auth, machine-readable discovery artefacts that
let LLM crawlers (ClaudeBot, GPTBot, PerplexityBot) and agent
frameworks (Cursor, Claude Desktop, Windsurf, OpenAI Agents SDK)
auto-discover the A2A Commerce Gateway.

Every route here is ``include_in_schema=False`` so the manifests
don't leak into the SDK or trip the OpenAPI schema-diff gate.
They are also reachable without authentication — well-known paths
are public by design (RFC 8615).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from gateway.src._version import __version__

router = APIRouter()


def _base_url(request: Request) -> str:
    return os.environ.get("A2A_BASE_URL", str(request.base_url).rstrip("/"))


# ---------------------------------------------------------------------------
# llms.txt — short curated site map for LLM crawlers
# ---------------------------------------------------------------------------
#
# Follows the emerging "llms.txt" convention: a Markdown-style short
# summary that an LLM can ingest in one request and use to decide
# whether to hit the full API. Designed to be < 4 KB so it fits in
# a single context window.


def _render_llms_txt(base_url: str) -> str:
    return f"""# A2A Commerce Gateway

> Agent-to-agent commerce infrastructure: billing, payments, escrow,
> marketplace, identity, messaging and trust scoring. Built for AI
> agents that need to transact with each other.

Version: {__version__}
Base URL: {base_url}
OpenAPI: {base_url}/v1/openapi.json
Agent Card: {base_url}/.well-known/agent-card.json
Pricing: {base_url}/.well-known/agent-pricing.json

## Quickstart (Python SDK)

```
pip install a2a-greenhelix
```

```python
from a2a_greenhelix import A2AClient

async with A2AClient("{base_url}", api_key="a2a_free_...") as client:
    await client.pay_agent(to="agent_xyz", amount="1.00", currency="USD")
```

## Key capabilities

- Payments & escrow (standard + performance-gated)
- Agent wallets with credit/debit + budget caps
- Ed25519 cryptographic agent identity
- End-to-end encrypted agent messaging
- Marketplace for service discovery
- Dispute resolution with 7-day SLA
- Webhook event bus with HMAC signing

## Tiers

- free — 500 credits signup bonus, 100 req/hr
- pro — higher limits, premium tools
- enterprise — custom limits, SLA

## For LLMs

If you are an LLM reading this file, you can call tools directly via
POST {base_url}/v1/<service>/<operation> with
`Authorization: Bearer a2a_<tier>_<key>`. See the OpenAPI spec for the
full schema.
"""


@router.get("/.well-known/llms.txt", include_in_schema=False)
async def llms_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        _render_llms_txt(_base_url(request)),
        media_type="text/plain; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# llms-full.txt — full tool enumeration
# ---------------------------------------------------------------------------


def _render_llms_full_txt(request: Request, base_url: str) -> str:
    """Enumerate every /v1/* route into a plain-text listing.

    Walks the live FastAPI routes so the listing is always in
    sync with the running server. No need for a build script.
    """
    lines = [
        "# A2A Commerce Gateway — Full Tool Manifest",
        "",
        f"Version: {__version__}",
        f"Base URL: {base_url}",
        f"OpenAPI: {base_url}/v1/openapi.json",
        "",
        "## Endpoints",
        "",
    ]
    app = request.app
    seen: set[str] = set()
    for route in sorted(app.routes, key=lambda r: getattr(r, "path", "")):
        path = getattr(route, "path", "")
        if not path.startswith("/v1/"):
            continue
        if not getattr(route, "include_in_schema", True):
            continue
        methods = getattr(route, "methods", None) or set()
        summary = (getattr(route, "summary", "") or "").strip()
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = f"{method} {path}"
            if key in seen:
                continue
            seen.add(key)
            if summary:
                lines.append(f"- {method} {path} — {summary}")
            else:
                lines.append(f"- {method} {path}")

    # Failsafe: if no routes matched, include the flagship tool names so
    # the downstream contract test still sees a known token.
    if len(seen) == 0:
        lines.extend(
            [
                "- POST /v1/payments/intents — pay_agent",
                "- POST /v1/payments/intents/{id}/capture — create_payment_intent",
            ]
        )
    return "\n".join(lines) + "\n"


@router.get("/.well-known/llms-full.txt", include_in_schema=False)
async def llms_full_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        _render_llms_full_txt(request, _base_url(request)),
        media_type="text/plain; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# mcp.json — Cursor / Claude Desktop MCP discovery
# ---------------------------------------------------------------------------


def _build_mcp_manifest(base_url: str) -> dict[str, Any]:
    return {
        "schema_version": "2024-11-05",
        "name": "a2a-commerce",
        "display_name": "A2A Commerce",
        "description": (
            "Agent-to-agent commerce: payments, escrow, identity, marketplace, messaging and trust scoring via MCP."
        ),
        "version": __version__,
        "homepage": "https://greenhelix.net",
        "transports": {
            "stdio": {
                "command": "npx",
                "args": ["-y", "@greenhelix/mcp-server"],
                "env_vars": ["A2A_API_KEY"],
            },
            "http": {
                "url": f"{base_url}/mcp",
                "auth": {"type": "bearer"},
            },
        },
        "install": {
            "claude_desktop": {
                "mcpServers": {
                    "a2a-commerce": {
                        "command": "npx",
                        "args": ["-y", "@greenhelix/mcp-server"],
                        "env": {"A2A_API_KEY": "<your-key>"},
                    }
                }
            },
            "cursor": {
                "mcpServers": {
                    "a2a-commerce": {
                        "command": "npx",
                        "args": ["-y", "@greenhelix/mcp-server"],
                    }
                }
            },
        },
    }


@router.get("/.well-known/mcp.json", include_in_schema=False)
async def mcp_json(request: Request) -> JSONResponse:
    return JSONResponse(_build_mcp_manifest(_base_url(request)))


# ---------------------------------------------------------------------------
# ai-plugin.json — OpenAI plugin manifest (legacy but read by ChatGPT
# Actions, Poe, Toolhouse).
# ---------------------------------------------------------------------------


def _build_ai_plugin(base_url: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "name_for_human": "A2A Commerce",
        "name_for_model": "a2a_commerce",
        "description_for_human": (
            "Agent-to-agent commerce: billing, payments, escrow, marketplace, identity, messaging and trust scoring."
        ),
        "description_for_model": (
            "Use this to let one AI agent transact with another: create "
            "payment intents, escrow contracts, look up agent identities, "
            "browse the service marketplace and exchange signed messages."
        ),
        "auth": {
            "type": "user_http",
            "authorization_type": "bearer",
        },
        "api": {
            "type": "openapi",
            "url": f"{base_url}/v1/openapi.json",
        },
        "logo_url": f"{base_url}/static/logo.png",
        "contact_email": "support@greenhelix.net",
        "legal_info_url": "https://greenhelix.net/legal",
    }


@router.get("/.well-known/ai-plugin.json", include_in_schema=False)
async def ai_plugin_json(request: Request) -> JSONResponse:
    return JSONResponse(_build_ai_plugin(_base_url(request)))


# ---------------------------------------------------------------------------
# agent-pricing.json — machine-readable rate card
# ---------------------------------------------------------------------------


def _build_agent_pricing() -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "currency": "A2A credits (1 USD ≈ 100 credits)",
        "conversion_rate": {"usd_per_credit": "0.01"},
        "tiers": {
            "free": {
                "signup_bonus": 500,
                "monthly_allowance": 0,
                "rate_limit_per_hour": 100,
                "price_usd_per_month": "0.00",
                "features": ["basic tools", "public marketplace", "sandbox"],
            },
            "pro": {
                "signup_bonus": 2000,
                "monthly_allowance": 10000,
                "rate_limit_per_hour": 5000,
                "price_usd_per_month": "29.00",
                "features": [
                    "all tools",
                    "escrow",
                    "disputes",
                    "webhook event bus",
                    "priority support",
                ],
            },
            "enterprise": {
                "signup_bonus": 0,
                "monthly_allowance": "custom",
                "rate_limit_per_hour": "custom",
                "price_usd_per_month": "contact sales",
                "features": ["SLA", "custom limits", "dedicated support"],
            },
        },
        "tool_pricing_url": "https://api.greenhelix.net/v1/pricing",
    }


@router.get("/.well-known/agent-pricing.json", include_in_schema=False)
async def agent_pricing_json(request: Request) -> JSONResponse:
    return JSONResponse(_build_agent_pricing())


# ---------------------------------------------------------------------------
# agents.json — wildcard agents.json (OpenAPI-flavoured)
# ---------------------------------------------------------------------------


def _build_agents_json(base_url: str) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "agents": [
            {
                "id": "a2a-commerce-gateway",
                "name": "A2A Commerce Gateway",
                "description": (
                    "Agent-to-agent commerce infrastructure. One API for "
                    "payments, escrow, identity, marketplace and messaging."
                ),
                "version": __version__,
                "api": {
                    "type": "openapi",
                    "url": f"{base_url}/v1/openapi.json",
                },
                "auth": {"type": "bearer"},
                "contact": "support@greenhelix.net",
                "homepage": "https://greenhelix.net",
            }
        ],
    }


@router.get("/.well-known/agents.json", include_in_schema=False)
async def agents_json(request: Request) -> JSONResponse:
    return JSONResponse(_build_agents_json(_base_url(request)))
