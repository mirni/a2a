"""Starlette application factory."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Route

from gateway.src.lifespan import lifespan
from gateway.src.routes.execute import routes as execute_routes
from gateway.src.routes.health import routes as health_routes
from gateway.src.routes.pricing import routes as pricing_routes


def create_app() -> Starlette:
    """Build and return the Starlette application."""
    all_routes: list[Route] = []
    all_routes.extend(health_routes)
    all_routes.extend(pricing_routes)
    all_routes.extend(execute_routes)

    app = Starlette(
        routes=all_routes,
        lifespan=lifespan,
    )
    return app
