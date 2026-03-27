"""Starlette application factory."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from gateway.src.lifespan import lifespan
from gateway.src.middleware import CorrelationIDMiddleware, metrics_handler
from gateway.src.openapi import openapi_handler
from gateway.src.routes.execute import routes as execute_routes
from gateway.src.routes.health import routes as health_routes
from gateway.src.routes.pricing import routes as pricing_routes
from gateway.src.signing import signing_key_handler
from gateway.src.swagger import swagger_ui_handler


# ---------------------------------------------------------------------------
# Backward-compatibility redirects: old paths -> /v1/ paths (301)
# ---------------------------------------------------------------------------

async def _redirect_health(request: Request) -> Response:
    return RedirectResponse(url="/v1/health", status_code=301)


async def _redirect_pricing(request: Request) -> Response:
    return RedirectResponse(url="/v1/pricing", status_code=301)


async def _redirect_pricing_tool(request: Request) -> Response:
    tool = request.path_params["tool"]
    return RedirectResponse(url=f"/v1/pricing/{tool}", status_code=301)


async def _redirect_execute(request: Request) -> Response:
    return RedirectResponse(url="/v1/execute", status_code=307)


_redirect_routes = [
    Route("/health", _redirect_health, methods=["GET"]),
    Route("/pricing", _redirect_pricing, methods=["GET"]),
    Route("/pricing/{tool}", _redirect_pricing_tool, methods=["GET"]),
    Route("/execute", _redirect_execute, methods=["POST"]),
]


def create_app() -> Starlette:
    """Build and return the Starlette application."""
    all_routes: list[Route] = []

    # Versioned routes
    all_routes.extend(health_routes)
    all_routes.extend(pricing_routes)
    all_routes.extend(execute_routes)

    # New routes
    all_routes.append(Route("/v1/openapi.json", openapi_handler, methods=["GET"]))
    all_routes.append(Route("/v1/metrics", metrics_handler, methods=["GET"]))
    all_routes.append(Route("/v1/signing-key", signing_key_handler, methods=["GET"]))
    all_routes.append(Route("/docs", swagger_ui_handler, methods=["GET"]))

    # Backward-compatibility redirects
    all_routes.extend(_redirect_routes)

    app = Starlette(
        routes=all_routes,
        lifespan=lifespan,
    )

    # Add middleware
    app.add_middleware(CorrelationIDMiddleware)

    return app
