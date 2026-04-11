"""Tests for /.well-known/* discovery endpoints.

Covers the A3 distribution-strategy deliverables: one file per
discovery manifest so LLM crawlers and agent frameworks can
auto-discover the A2A Commerce Gateway without human configuration.

These routes deliberately bypass authentication (they are
public-by-design) and are not included in the OpenAPI schema
(``include_in_schema=False``) so they don't pollute the SDK.
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio


class TestWellKnownEndpoints:
    async def test_llms_txt_served(self, client):
        """``/.well-known/llms.txt`` returns a short curated site map."""
        resp = await client.get("/.well-known/llms.txt")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        # Must name the product and link the OpenAPI dump.
        assert "A2A Commerce Gateway" in body
        assert "/v1/openapi.json" in body or "openapi" in body.lower()

    async def test_llms_full_txt_served(self, client):
        """``/.well-known/llms-full.txt`` enumerates the full route set."""
        resp = await client.get("/.well-known/llms-full.txt")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        # Must contain the flagship payments and identity route prefixes.
        assert "/v1/payments" in body
        assert "/v1/identity" in body
        # Must contain at least one HTTP method marker.
        assert any(m in body for m in ("GET", "POST", "PUT", "DELETE"))

    async def test_mcp_json_served(self, client):
        """``/.well-known/mcp.json`` advertises the MCP server location."""
        resp = await client.get("/.well-known/mcp.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("name") == "a2a-commerce"
        # Must ship both stdio and http transports.
        transports = body.get("transports", {})
        assert "stdio" in transports or "http" in transports

    async def test_ai_plugin_json_served(self, client):
        """``/.well-known/ai-plugin.json`` is the legacy OpenAI plugin manifest."""
        resp = await client.get("/.well-known/ai-plugin.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"] == "v1"
        assert body["name_for_human"]
        assert body["api"]["type"] == "openapi"

    async def test_agent_pricing_json_served(self, client):
        """``/.well-known/agent-pricing.json`` is the machine-readable rate card."""
        resp = await client.get("/.well-known/agent-pricing.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "currency" in body
        assert "tiers" in body
        assert "free" in body["tiers"]
        assert "pro" in body["tiers"]

    async def test_agents_json_served(self, client):
        """``/.well-known/agents.json`` — wildcard agents.json format."""
        resp = await client.get("/.well-known/agents.json")
        assert resp.status_code == 200
        body = resp.json()
        assert body["schema_version"].startswith("v")
        assert isinstance(body.get("agents"), list)
        assert body["agents"], "agents array must not be empty"

    async def test_all_endpoints_bypass_auth(self, client):
        """Well-known endpoints must be reachable without an API key."""
        paths = [
            "/.well-known/llms.txt",
            "/.well-known/llms-full.txt",
            "/.well-known/mcp.json",
            "/.well-known/ai-plugin.json",
            "/.well-known/agent-pricing.json",
            "/.well-known/agents.json",
        ]
        for path in paths:
            resp = await client.get(path)  # no Authorization header
            assert resp.status_code == 200, f"{path} should be public but returned {resp.status_code}"

    async def test_all_endpoints_hidden_from_openapi(self, app):
        """Well-known endpoints should NOT appear in the OpenAPI schema.

        Otherwise the SDK generator will emit dead client methods and
        the schema-diff gate will flag every addition.
        """
        schema = app.openapi()
        paths = schema.get("paths", {})
        for path in paths:
            assert not path.startswith("/.well-known/"), f"well-known path leaked into OpenAPI schema: {path}"

    async def test_json_manifests_parse_as_valid_json(self, client):
        """Defensive: each JSON manifest must round-trip through json.loads."""
        json_paths = [
            "/.well-known/mcp.json",
            "/.well-known/ai-plugin.json",
            "/.well-known/agent-pricing.json",
            "/.well-known/agents.json",
        ]
        for path in json_paths:
            resp = await client.get(path)
            assert resp.status_code == 200
            # This raises if the body is not valid JSON.
            json.loads(resp.text)
