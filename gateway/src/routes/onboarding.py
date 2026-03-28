"""GET /v1/onboarding — Agentic Onboarding endpoint.

Returns an enriched OpenAPI 3.1.0 spec with:
- Rich per-tool examples from catalog
- Quickstart guide in x-onboarding extension
- Authentication instructions
- Rate limit documentation per tier
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.src.openapi import generate_openapi_spec


def _build_onboarding_extension() -> dict:
    """Build the x-onboarding extension with quickstart guide and tier info."""
    return {
        "quickstart": [
            {
                "step": 1,
                "title": "Get an API key",
                "description": "Create an API key by calling the create_api_key tool or contacting an admin.",
                "example": 'curl -X POST /v1/execute -H "Content-Type: application/json" '
                '-d \'{"tool": "create_api_key", "params": {"agent_id": "my-agent"}}\'',
            },
            {
                "step": 2,
                "title": "Check your balance",
                "description": "Verify your credit balance before making tool calls.",
                "example": 'curl -X POST /v1/execute -H "Authorization: Bearer YOUR_KEY" '
                '-d \'{"tool": "get_balance", "params": {"agent_id": "my-agent"}}\'',
            },
            {
                "step": 3,
                "title": "Browse available tools",
                "description": "List all available tools with pricing via the pricing endpoint.",
                "example": "curl /v1/pricing",
            },
            {
                "step": 4,
                "title": "Execute a tool",
                "description": "Call any tool using the execute endpoint with your API key.",
                "example": 'curl -X POST /v1/execute -H "Authorization: Bearer YOUR_KEY" '
                '-d \'{"tool": "search_services", "params": {"query": "code review"}}\'',
            },
        ],
        "authentication": {
            "header": "Authorization: Bearer <api_key>",
            "alternative_header": "X-API-Key: <api_key>",
            "description": "Include your API key in the Authorization header using Bearer scheme.",
        },
        "tiers": {
            "free": {
                "rate_limit_per_hour": 100,
                "description": "Basic access for evaluation and small workloads.",
            },
            "starter": {
                "rate_limit_per_hour": 500,
                "description": "For individual agents with moderate usage.",
            },
            "pro": {
                "rate_limit_per_hour": 2000,
                "description": "For production agents with higher throughput needs.",
            },
            "enterprise": {
                "rate_limit_per_hour": 10000,
                "description": "Unlimited access with priority support.",
            },
        },
        "support": {
            "docs": "/docs",
            "openapi_spec": "/v1/openapi.json",
            "health_check": "/v1/health",
        },
    }


async def onboarding_handler(request: Request) -> JSONResponse:
    """Return enriched OpenAPI spec with onboarding guide."""
    spec = generate_openapi_spec()

    # Inject x-onboarding extension into info section
    spec["info"]["x-onboarding"] = _build_onboarding_extension()

    return JSONResponse(spec)


routes = [Route("/v1/onboarding", onboarding_handler, methods=["GET"])]
