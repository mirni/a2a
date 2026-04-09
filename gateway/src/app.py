"""FastAPI application factory."""

from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import RedirectResponse, Response

from gateway.src._version import __version__
from gateway.src.errors import error_response
from gateway.src.lifespan import lifespan
from gateway.src.middleware import (
    AgentIdLengthMiddleware,
    BodySizeLimitMiddleware,
    CorrelationIDMiddleware,
    HttpsEnforcementMiddleware,
    MetricsMiddleware,
    PublicRateLimitMiddleware,
    RequestTimeoutMiddleware,
    SecurityHeadersMiddleware,
    metrics_handler,
)
from gateway.src.openapi import generate_openapi_spec
from gateway.src.routes.agent_card import router as agent_card_router
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
from gateway.src.routes.v1.gatekeeper import router as gatekeeper_router
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
    app.include_router(agent_card_router)
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
    app.include_router(gatekeeper_router)
    app.include_router(_redirect_router)

    # Exception handler for deps._ResponseError (auth/rate-limit failures in Depends)
    from gateway.src.deps.tool_context import _ResponseError

    @app.exception_handler(_ResponseError)
    async def _response_error_handler(request: Request, exc: _ResponseError) -> Response:
        return exc.response

    # Wrap FastAPI's default 422 validation errors in RFC 9457 format
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        return await error_response(422, detail, "validation_error", request=request)

    # Wrap 405 Method Not Allowed in RFC 9457 format
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        return await error_response(exc.status_code, exc.detail, "http_error", request=request)

    # Catch-all for uncaught exceptions: return RFC 9457 JSON, not
    # Starlette's plain-text default. This guards against lazy-import
    # ModuleNotFoundError and other crashes escaping route handlers
    # (v0.9.3 jsonschema regression).
    #
    # Audit H1: route handlers that forget to wrap product exceptions
    # (e.g. InsufficientCreditsError → 402) used to surface as generic
    # 500. Delegate to handle_product_exception first so product errors
    # get their proper HTTP status code regardless of which route raised.
    import logging as _logging

    from gateway.src.errors import handle_product_exception

    _gw_logger = _logging.getLogger("a2a.gateway")

    # Exception types whose names are mapped inside handle_product_exception.
    # Any other exception is treated as truly unexpected (500).
    _PRODUCT_EXC_NAMES = frozenset(
        {
            "InvalidKeyError",
            "ExpiredKeyError",
            "PaywallAuthError",
            "KeyScopeError",
            "TierInsufficientError",
            "RateLimitError",
            "RateLimitExceededError",
            "SpendCapExceededError",
            "InsufficientCreditsError",
            "InsufficientBalanceError",
            "ServiceNotFoundError",
            "ServerNotFoundError",
            "IntentNotFoundError",
            "EscrowNotFoundError",
            "WalletNotFoundError",
            "WalletFrozenError",
            "SubscriptionNotFoundError",
            "AgentNotFoundError",
            "InvalidStateError",
            "DuplicateIntentError",
            "DuplicateServiceError",
            "AgentAlreadyExistsError",
            "InvalidMetricError",
            "ToolValidationError",
            "ToolForbiddenError",
            "ToolNotFoundError",
            "NegativeCostError",
            "DisputeNotFoundError",
            "DisputeStateError",
            "OrgNotFoundError",
            "MemberNotFoundError",
            "LastOwnerError",
            "SubscriptionStateError",
            "PaymentError",
            "X402VerificationError",
            "X402ReplayError",
        }
    )

    @app.exception_handler(Exception)
    async def _uncaught_exception_handler(request: Request, exc: Exception) -> Response:
        exc_name = type(exc).__name__
        if exc_name in _PRODUCT_EXC_NAMES:
            # Known product error — map to its proper HTTP status.
            return await handle_product_exception(request, exc)
        _gw_logger.exception("Unhandled exception in %s %s: %s", request.method, request.url.path, exc_name)
        # Generic detail — do not leak exception message (may contain secrets/paths)
        return await error_response(500, "Internal server error", "internal_error", request=request)

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
    # HttpsEnforcementMiddleware comes before AgentIdLengthMiddleware so that
    # plaintext rejection happens before any app logic — but still below the
    # outermost CorrelationIDMiddleware so redirects carry a request id.
    app.add_middleware(HttpsEnforcementMiddleware)
    app.add_middleware(AgentIdLengthMiddleware)
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
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Payment", "Idempotency-Key"],
        )

    app.add_middleware(CorrelationIDMiddleware)

    return app
