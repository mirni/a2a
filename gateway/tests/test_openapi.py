"""Tests for the OpenAPI spec endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_openapi_spec(client):
    """GET /v1/openapi.json should return a valid OpenAPI 3.1 spec."""
    resp = await client.get("/v1/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["openapi"] == "3.1.0"
    assert data["info"]["title"] == "A2A Commerce Gateway"
    assert "/health" in data["paths"] or "/v1/health" in str(data["paths"])
    assert "components" in data
    assert "schemas" in data["components"]


@pytest.mark.asyncio
async def test_openapi_has_tools(client):
    """OpenAPI spec should include tool examples in POST /v1/execute."""
    resp = await client.get("/v1/openapi.json")
    data = resp.json()
    execute_path = data["paths"].get("/v1/execute", {})
    post = execute_path.get("post", {})
    # Should have examples for each tool
    examples = post.get("requestBody", {}).get("content", {}).get("application/json", {}).get("examples", {})
    assert len(examples) > 0
    assert "get_balance" in examples
