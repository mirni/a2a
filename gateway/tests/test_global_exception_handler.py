"""Tests for the global uncaught-exception handler.

Regression safety: any Exception escaping a route must be returned as
RFC 9457 JSON, not Starlette's plain-text 500. This is the last line of
defense against issues like the v0.9.3 jsonschema ModuleNotFoundError
that escaped error_response() and surfaced as plain-text 500 to clients.
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def app_with_crash_route(app):
    """Register a route that always raises, for exception-handler testing."""
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/v1/__test_crash")
    async def crash() -> None:
        raise RuntimeError("synthetic crash for exception-handler test")

    @router.get("/v1/__test_import_crash")
    async def import_crash() -> None:
        # Simulate the v0.9.3 jsonschema regression: lazy import fails
        import this_module_does_not_exist_xyz  # noqa: F401

    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_uncaught_runtime_error_returns_rfc9457_json(app_with_crash_route) -> None:
    """Uncaught RuntimeError must return application/problem+json, not text/plain."""
    import httpx

    transport = httpx.ASGITransport(app=app_with_crash_route, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/__test_crash")

    assert resp.status_code == 500, f"expected 500, got {resp.status_code}"
    # Must NOT be Starlette's plain-text default
    ct = resp.headers.get("content-type", "")
    assert "problem+json" in ct or "application/json" in ct, (
        f"expected structured JSON content-type, got {ct!r} body={resp.text[:200]!r}"
    )
    body = resp.json()
    assert body["status"] == 500
    assert "type" in body
    assert "title" in body
    assert "detail" in body


@pytest.mark.asyncio
async def test_uncaught_import_error_returns_rfc9457_json(app_with_crash_route) -> None:
    """ModuleNotFoundError (like jsonschema) must return structured JSON."""
    import httpx

    transport = httpx.ASGITransport(app=app_with_crash_route, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/__test_import_crash")

    assert resp.status_code == 500
    ct = resp.headers.get("content-type", "")
    assert "problem+json" in ct or "application/json" in ct, (
        f"expected structured JSON, got {ct!r} body={resp.text[:200]!r}"
    )
    body = resp.json()
    assert body["status"] == 500


@pytest.mark.asyncio
async def test_500_response_does_not_leak_traceback(app_with_crash_route) -> None:
    """500 response must not contain file paths, stack frames, or module names."""
    import httpx

    transport = httpx.ASGITransport(app=app_with_crash_route, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/__test_crash")

    body_text = resp.text
    # No paths, no python file names, no 'Traceback', no 'File "..."'
    assert "Traceback" not in body_text
    assert 'File "' not in body_text
    assert ".py" not in body_text
    assert "synthetic crash" not in body_text, (
        "detail must not echo internal exception messages that could leak secrets"
    )
