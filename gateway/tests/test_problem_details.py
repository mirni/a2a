"""Tests for RFC 9457 Problem Details error format (T4).

All error responses must:
- Use Content-Type: application/problem+json
- Include type (URI), title, status, detail fields
- Include instance field (request path)
- NOT include legacy success/error/request_id body fields
- X-Request-ID in header (not body)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Route-level errors via error_response()
# ---------------------------------------------------------------------------


async def test_error_content_type_is_problem_json(client, api_key):
    """Error responses must have Content-Type: application/problem+json."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"] == "application/problem+json"


async def test_error_body_has_rfc9457_fields(client, api_key):
    """Error body must contain type, title, status, detail."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    body = resp.json()
    assert "type" in body
    assert "title" in body
    assert "status" in body
    assert "detail" in body
    assert body["status"] == 400
    assert body["type"].startswith("https://")
    assert body["type"].endswith("/unknown-tool")


async def test_error_body_has_instance(client, api_key):
    """Error body must include instance (request path)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    body = resp.json()
    assert body["instance"] == "/v1/execute"


async def test_error_body_no_legacy_fields(client, api_key):
    """Error body must NOT contain legacy success/error/request_id fields."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    body = resp.json()
    assert "success" not in body
    assert "error" not in body
    assert "request_id" not in body


async def test_error_request_id_in_header(client, api_key):
    """X-Request-ID must be in the response header for errors."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) > 0


async def test_401_uses_problem_details(client):
    """401 missing key error uses RFC 9457 format."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "x"}},
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["status"] == 401
    assert body["type"].endswith("/missing-key")
    assert "success" not in body


async def test_product_exception_uses_problem_details(client, api_key):
    """Product exceptions (e.g. not found) use RFC 9457."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["status"] == 404
    assert "type" in body


async def test_422_validation_error_uses_problem_details(client, api_key):
    """422 validation errors use RFC 9457."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}, "extra_field": True},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["status"] == 422
    assert body["type"].endswith("/validation-error")


# ---------------------------------------------------------------------------
# Middleware-level errors (raw ASGI)
# ---------------------------------------------------------------------------


async def test_413_middleware_uses_problem_details(client, api_key):
    """413 from BodySizeLimitMiddleware uses RFC 9457 format."""
    huge_body = b"x" * (2 * 1024 * 1024)  # 2MB > 1MB limit
    resp = await client.post(
        "/v1/execute",
        content=huge_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Content-Length": str(len(huge_body)),
        },
    )
    assert resp.status_code == 413
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["status"] == 413
    assert "type" in body
    assert "success" not in body


async def test_429_middleware_uses_problem_details(client, app):
    """429 from PublicRateLimitMiddleware uses RFC 9457 format."""
    from gateway.src.rate_limit_headers import PublicRateLimiter

    limiter = PublicRateLimiter(limit=1, window_seconds=3600)
    app.state.public_rate_limiter = limiter

    # First request to exhaust the limit
    await client.get("/v1/pricing")
    # Second request should be rate-limited
    resp = await client.get("/v1/pricing")

    assert resp.status_code == 429
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["status"] == 429
    assert "type" in body
    assert "success" not in body


# ---------------------------------------------------------------------------
# Pricing endpoint error
# ---------------------------------------------------------------------------


async def test_pricing_404_uses_problem_details(client):
    """GET /v1/pricing/{unknown} returns RFC 9457 error."""
    resp = await client.get("/v1/pricing/nonexistent_tool_xyz")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["status"] == 404
    assert "type" in body
    assert "success" not in body
