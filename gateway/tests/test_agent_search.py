"""Tests for agent search/discovery by capabilities (TDD).

Agents should be discoverable by the tools/services they provide,
their categories, and tags.
"""

from __future__ import annotations

import pytest
from marketplace_src.models import ServiceCreate

pytestmark = pytest.mark.asyncio


class TestSearchAgentsByCapability:
    """Test searching agents by capability keywords."""

    async def test_tool_exists(self, client, api_key):
        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "data"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_search_by_tool_name(self, client, api_key, app):
        """Should find agents whose services include a matching tool."""
        ctx = app.state.ctx
        await ctx.marketplace.register_service(ServiceCreate(
            provider_id="agent-data",
            name="Data Pipeline",
            description="ETL service",
            category="data",
            tools=["extract_csv", "transform_json", "load_db"],
        ))
        await ctx.marketplace.register_service(ServiceCreate(
            provider_id="agent-ml",
            name="ML Inference",
            description="ML model serving",
            category="ai",
            tools=["predict", "classify"],
        ))

        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "csv"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        agents = data["result"]["agents"]
        assert any(a["agent_id"] == "agent-data" for a in agents)
        assert not any(a["agent_id"] == "agent-ml" for a in agents)

    async def test_search_by_category(self, client, api_key, app):
        """Should find agents providing services in a given category."""
        ctx = app.state.ctx
        await ctx.marketplace.register_service(ServiceCreate(
            provider_id="agent-ai",
            name="AI Service",
            description="AI capabilities",
            category="artificial_intelligence",
        ))

        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "artificial_intelligence"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agents = resp.json()["result"]["agents"]
        assert any(a["agent_id"] == "agent-ai" for a in agents)

    async def test_search_by_description(self, client, api_key, app):
        """Should match against service description."""
        ctx = app.state.ctx
        await ctx.marketplace.register_service(ServiceCreate(
            provider_id="agent-translate",
            name="Translator",
            description="Real-time language translation for 50+ languages",
            category="nlp",
        ))

        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "translation"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agents = resp.json()["result"]["agents"]
        assert any(a["agent_id"] == "agent-translate" for a in agents)

    async def test_search_respects_limit(self, client, api_key, app):
        """Should respect the limit parameter."""
        ctx = app.state.ctx
        for i in range(5):
            await ctx.marketplace.register_service(ServiceCreate(
                provider_id=f"agent-search-{i}",
                name=f"Service {i}",
                description="Common description for all",
                category="general",
            ))

        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "Common", "limit": 3}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agents = resp.json()["result"]["agents"]
        assert len(agents) <= 3

    async def test_search_returns_agent_info(self, client, api_key, app):
        """Each result should include agent_id and services."""
        ctx = app.state.ctx
        await ctx.marketplace.register_service(ServiceCreate(
            provider_id="agent-info",
            name="Info Service",
            description="A service for info",
            category="general",
            tools=["get_info"],
        ))

        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "info"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        agents = resp.json()["result"]["agents"]
        agent = [a for a in agents if a["agent_id"] == "agent-info"][0]
        assert "services" in agent
        assert len(agent["services"]) >= 1
        assert agent["services"][0]["name"] == "Info Service"

    async def test_empty_results(self, client, api_key):
        """Should return empty list when no matches."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "search_agents", "params": {"query": "zzz_nonexistent_zzz"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["agents"] == []
