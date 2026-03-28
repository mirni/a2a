"""Tests for GET /v1/onboarding — Agentic Onboarding endpoint.

Verifies that the onboarding endpoint returns an enriched OpenAPI 3.1 spec
with quickstart guide, rich examples, and authentication instructions.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestOnboardingEndpoint:
    """Tests for the onboarding endpoint."""

    async def test_returns_200(self, client):
        resp = await client.get("/v1/onboarding")
        assert resp.status_code == 200

    async def test_returns_valid_openapi_31(self, client):
        resp = await client.get("/v1/onboarding")
        data = resp.json()
        assert data["openapi"] == "3.1.0"
        assert "info" in data
        assert "paths" in data

    async def test_contains_onboarding_extension(self, client):
        resp = await client.get("/v1/onboarding")
        data = resp.json()
        info = data["info"]
        assert "x-onboarding" in info
        onboarding = info["x-onboarding"]
        assert "quickstart" in onboarding
        assert "authentication" in onboarding

    async def test_quickstart_has_steps(self, client):
        resp = await client.get("/v1/onboarding")
        onboarding = resp.json()["info"]["x-onboarding"]
        steps = onboarding["quickstart"]
        assert isinstance(steps, list)
        assert len(steps) >= 3

    async def test_authentication_instructions(self, client):
        resp = await client.get("/v1/onboarding")
        auth = resp.json()["info"]["x-onboarding"]["authentication"]
        assert "header" in auth
        assert "Bearer" in auth["header"]

    async def test_tools_have_examples(self, client):
        resp = await client.get("/v1/onboarding")
        paths = resp.json()["paths"]
        # Path may be /execute (relative to server /v1) or /v1/execute
        execute_path = "/execute" if "/execute" in paths else "/v1/execute"
        execute_post = paths.get(execute_path, {}).get("post", {})
        body = execute_post.get("requestBody", {})
        content = body.get("content", {}).get("application/json", {})
        examples = content.get("examples", {})
        # Should have at least some tools with examples
        assert len(examples) > 0

    async def test_includes_tier_info(self, client):
        resp = await client.get("/v1/onboarding")
        onboarding = resp.json()["info"]["x-onboarding"]
        assert "tiers" in onboarding
        tiers = onboarding["tiers"]
        assert "free" in tiers
        assert "pro" in tiers
