"""Negative tests — verify that invalid inputs are rejected properly.

Tests boundary conditions, malformed payloads, missing auth, and
error responses for critical endpoints.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestExecuteNegative:
    """Negative tests for POST /v1/execute."""

    async def test_missing_auth_returns_401(self, client):
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "x"}},
        )
        assert resp.status_code == 401

    async def test_invalid_api_key_returns_401(self, client):
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "x"}},
            headers={"Authorization": "Bearer invalid-key-abc123"},
        )
        assert resp.status_code == 401

    async def test_missing_tool_field_returns_4xx(self, client, api_key):
        resp = await client.post(
            "/v1/execute",
            json={"params": {"agent_id": "x"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (400, 422)

    async def test_unknown_tool_returns_4xx(self, client, api_key):
        resp = await client.post(
            "/v1/execute",
            json={"tool": "nonexistent_tool_xyz", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (400, 404)

    async def test_empty_body_returns_4xx(self, client, api_key):
        resp = await client.post(
            "/v1/execute",
            content=b"",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code in (400, 422)

    async def test_malformed_json_returns_4xx(self, client, api_key):
        resp = await client.post(
            "/v1/execute",
            content=b"{not valid json",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code in (400, 422)


class TestBatchNegative:
    """Negative tests for POST /v1/batch."""

    async def test_missing_auth_returns_401(self, client):
        resp = await client.post(
            "/v1/batch",
            json={"calls": [{"tool": "get_balance", "params": {"agent_id": "x"}}]},
        )
        assert resp.status_code == 401

    async def test_empty_calls_returns_4xx_or_empty(self, client, api_key):
        resp = await client.post(
            "/v1/batch",
            json={"calls": []},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (200, 400, 422)

    async def test_missing_calls_field_returns_4xx(self, client, api_key):
        resp = await client.post(
            "/v1/batch",
            json={"something": "else"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (400, 422)


class TestHealthNegative:
    """Negative tests for health endpoints."""

    async def test_health_post_returns_405(self, client):
        resp = await client.post("/v1/health")
        assert resp.status_code == 405

    async def test_nonexistent_route_returns_404(self, client):
        resp = await client.get("/v1/does-not-exist")
        assert resp.status_code in (404, 405)


class TestPricingNegative:
    """Negative tests for pricing endpoints."""

    async def test_pricing_nonexistent_tool_returns_404(self, client):
        resp = await client.get("/v1/pricing/nonexistent_tool_xyz")
        assert resp.status_code == 404


class TestSSENegative:
    """Negative tests for SSE streaming endpoint."""

    async def test_sse_missing_auth_returns_401(self, client):
        resp = await client.get("/v1/events/stream")
        assert resp.status_code == 401

    async def test_sse_invalid_key_returns_401(self, client):
        resp = await client.get(
            "/v1/events/stream",
            headers={"Authorization": "Bearer bad-key"},
        )
        assert resp.status_code == 401
