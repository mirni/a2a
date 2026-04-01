"""FastAPI application factory."""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response

from gateway.src._version import __version__
from gateway.src.lifespan import lifespan
from gateway.src.middleware import (
    BodySizeLimitMiddleware,
    CorrelationIDMiddleware,
    MetricsMiddleware,
    PublicRateLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
    metrics_handler,
)
from gateway.src.openapi import generate_openapi_spec
from gateway.src.routes.batch import router as batch_router
from gateway.src.routes.execute import router as execute_router
from gateway.src.routes.health import router as health_router
from gateway.src.routes.onboarding import router as onboarding_router
from gateway.src.routes.pricing import router as pricing_router
from gateway.src.routes.register import router as register_router
from gateway.src.routes.sse import router as sse_router
from gateway.src.routes.v1.billing import router as billing_router
from gateway.src.routes.v1.disputes import router as disputes_router
from gateway.src.routes.v1.identity import router as identity_router
from gateway.src.routes.v1.infra import router as infra_router
from gateway.src.routes.v1.marketplace import router as marketplace_router
from gateway.src.routes.v1.messaging import router as messaging_router
from gateway.src.routes.v1.payments import router as payments_router
from gateway.src.routes.v1.trust import router as trust_router
from gateway.src.routes.websocket import router as ws_router
from gateway.src.signing import signing_key_handler
from gateway.src.stripe_checkout import router as checkout_router

# ---------------------------------------------------------------------------
# Backward-compatibility redirects: old paths -> /v1/ paths (301)
# ---------------------------------------------------------------------------

_redirect_router = APIRouter()


@_redirect_router.get("/health")
async def _redirect_health(request: Request) -> Response:
    return RedirectResponse(url="/v1/health", status_code=301)


@_redirect_router.get("/pricing")
async def _redirect_pricing(request: Request) -> Response:
    return RedirectResponse(url="/v1/pricing", status_code=301)


@_redirect_router.get("/pricing/{tool}")
async def _redirect_pricing_tool(request: Request) -> Response:
    tool = request.path_params["tool"]
    return RedirectResponse(url=f"/v1/pricing/{tool}", status_code=301)


@_redirect_router.post("/execute")
async def _redirect_execute(request: Request) -> Response:
    return RedirectResponse(url="/v1/execute", status_code=307)


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(
        title="A2A Commerce Gateway",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/v1/openapi.json",
    )

    # Include all routers
    app.include_router(health_router)
    app.include_router(pricing_router)
    app.include_router(execute_router)
    app.include_router(batch_router)
    app.include_router(sse_router)
    app.include_router(ws_router)
    app.include_router(onboarding_router)
    app.include_router(register_router)
    app.include_router(checkout_router)
    app.include_router(billing_router)
    app.include_router(disputes_router)
    app.include_router(payments_router)
    app.include_router(identity_router)
    app.include_router(infra_router)
    app.include_router(marketplace_router)
    app.include_router(messaging_router)
    app.include_router(trust_router)
    app.include_router(_redirect_router)

    # Exception handler for deps._ResponseError (auth/rate-limit failures in Depends)
    from gateway.src.deps.tool_context import _ResponseError

    @app.exception_handler(_ResponseError)
    async def _response_error_handler(request: Request, exc: _ResponseError) -> Response:
        return exc.response

    # Standalone endpoints
    @app.get("/v1/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        # #28: IP allowlist for metrics endpoint
        allowed_raw = os.environ.get("METRICS_ALLOWED_IPS", "127.0.0.1,::1")
        allowed_ips = {ip.strip() for ip in allowed_raw.split(",") if ip.strip()}
        client_ip = request.client.host if request.client else None
        if allowed_ips and client_ip not in allowed_ips:
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "Forbidden"}, status_code=403)
        return await metrics_handler(request)

    @app.get("/v1/signing-key")
    async def signing_key(request: Request) -> Response:
        return await signing_key_handler(request)

    # Custom OpenAPI spec: merge tool examples from hand-written spec
    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        # Merge tool examples from hand-written spec
        old_spec = generate_openapi_spec()
        execute_examples = (
            old_spec["paths"]
            .get("/execute", {})
            .get("post", {})
            .get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("examples", {})
        )
        # Inject into auto-generated spec's /v1/execute path
        if "/v1/execute" in schema["paths"] and execute_examples:
            execute_post = schema["paths"]["/v1/execute"].get("post", {})
            execute_post.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {})[
                "examples"
            ] = execute_examples
        # Preserve components from hand-written spec
        if "components" in old_spec:
            schema.setdefault("components", {}).setdefault("schemas", {}).update(old_spec["components"]["schemas"])
            if "securitySchemes" in old_spec["components"]:
                schema["components"].setdefault("securitySchemes", {}).update(old_spec["components"]["securitySchemes"])
        # Preserve security from hand-written spec
        if "security" in old_spec:
            schema["security"] = old_spec["security"]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[assignment]

    # Add middleware (FastAPI wraps in reverse order: last add = outermost)
    app.add_middleware(PublicRateLimitMiddleware)
    app.add_middleware(RequestTimeoutMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(MetricsMiddleware)

    # P3-2: Security headers on every response
    app.add_middleware(SecurityHeadersMiddleware)

    # P3-3: CORS — only enabled when CORS_ALLOWED_ORIGINS is set
    cors_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if cors_origins_raw:
        allowed_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Payment", "Idempotency-Key"],
        )

    app.add_middleware(CorrelationIDMiddleware)

    return app
