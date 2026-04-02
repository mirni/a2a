"""Tests for P3-2 (security headers) and P3-3 (CORS middleware).

P3-2: Every HTTP response must include hardened security headers.
P3-3: CORS middleware with configurable allowed origins.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# P3-2  Security Headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_headers_x_content_type_options(client):
    """X-Content-Type-Options: nosniff must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_security_headers_x_frame_options(client):
    """X-Frame-Options: DENY must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["x-frame-options"] == "DENY"


@pytest.mark.asyncio
async def test_security_headers_strict_transport_security(client):
    """Strict-Transport-Security header must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains; preload"


@pytest.mark.asyncio
async def test_security_headers_content_security_policy(client):
    """Content-Security-Policy: default-src 'none' must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["content-security-policy"] == "default-src 'none'"


@pytest.mark.asyncio
async def test_security_headers_present_on_error_responses(client):
    """Security headers must also appear on error responses (e.g. 405)."""
    resp = await client.post("/v1/health")
    assert resp.status_code == 405
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains; preload"
    assert resp.headers["content-security-policy"] == "default-src 'none'"


@pytest.mark.asyncio
async def test_security_headers_referrer_policy(client):
    """Referrer-Policy: no-referrer must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_security_headers_permissions_policy(client):
    """Permissions-Policy must be present on every response."""
    resp = await client.get("/v1/health")
    assert resp.headers["permissions-policy"] == "geolocation=(), camera=(), microphone=()"


# ---------------------------------------------------------------------------
# P3-3  CORS Middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_no_header_when_no_origin(client):
    """Without an Origin header, no CORS headers should appear (same-origin)."""
    resp = await client.get("/v1/health")
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_cors_configured_origin_allowed(app, tmp_data_dir, monkeypatch):
    """When CORS_ALLOWED_ORIGINS includes the request origin, the
    access-control-allow-origin header must echo that origin back."""
    import httpx

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com,https://other.com")

    from gateway.src.app import create_app
    from gateway.src.lifespan import lifespan
    from gateway.src.routes.sse import SSEConfig

    cors_app = create_app()
    cors_app.state.sse_config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.3,
    )
    ctx_manager = lifespan(cors_app)
    await ctx_manager.__aenter__()
    try:
        transport = httpx.ASGITransport(app=cors_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                "/v1/health",
                headers={"Origin": "https://example.com"},
            )
            assert resp.headers["access-control-allow-origin"] == "https://example.com"
    finally:
        await ctx_manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cors_preflight_request(app, tmp_data_dir, monkeypatch):
    """OPTIONS preflight with a configured origin should succeed with CORS headers."""
    import httpx

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com")

    from gateway.src.app import create_app
    from gateway.src.lifespan import lifespan
    from gateway.src.routes.sse import SSEConfig

    cors_app = create_app()
    cors_app.state.sse_config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.3,
    )
    ctx_manager = lifespan(cors_app)
    await ctx_manager.__aenter__()
    try:
        transport = httpx.ASGITransport(app=cors_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.options(
                "/v1/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.status_code == 200
            assert resp.headers["access-control-allow-origin"] == "https://example.com"
    finally:
        await ctx_manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cors_disallowed_origin_rejected(app, tmp_data_dir, monkeypatch):
    """An Origin not in the allow-list must NOT receive CORS headers."""
    import httpx

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com")

    from gateway.src.app import create_app
    from gateway.src.lifespan import lifespan
    from gateway.src.routes.sse import SSEConfig

    cors_app = create_app()
    cors_app.state.sse_config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.3,
    )
    ctx_manager = lifespan(cors_app)
    await ctx_manager.__aenter__()
    try:
        transport = httpx.ASGITransport(app=cors_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                "/v1/health",
                headers={"Origin": "https://evil.com"},
            )
            assert "access-control-allow-origin" not in resp.headers
    finally:
        await ctx_manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_cors_default_no_origins(client):
    """By default (no CORS_ALLOWED_ORIGINS), cross-origin requests get no CORS headers."""
    resp = await client.get(
        "/v1/health",
        headers={"Origin": "https://example.com"},
    )
    assert "access-control-allow-origin" not in resp.headers
