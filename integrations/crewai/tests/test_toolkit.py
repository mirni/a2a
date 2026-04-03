"""TDD RED: Tests for toolkit.py — A2AToolkit."""

from __future__ import annotations

import pytest
from crewai.tools import BaseTool


class TestA2AToolkit:
    @pytest.mark.asyncio
    async def test_from_client_creates_toolkit(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client)
        assert isinstance(toolkit, A2AToolkit)

    @pytest.mark.asyncio
    async def test_get_tools_returns_list(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client)
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_tools_are_base_tool_instances(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client)
        for tool in toolkit.get_tools():
            assert isinstance(tool, BaseTool)

    @pytest.mark.asyncio
    async def test_tool_count_matches_catalog(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client)
        tools = toolkit.get_tools()
        # Sample catalog has 4 tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_calls_pricing(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        await A2AToolkit.from_client(mock_client)
        mock_client.pricing.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_filter(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client, services=["billing"])
        tools = toolkit.get_tools()
        # Sample catalog has 2 billing tools: get_balance, deposit
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"get_balance", "deposit"}

    @pytest.mark.asyncio
    async def test_service_filter_multiple(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client, services=["billing", "marketplace"])
        tools = toolkit.get_tools()
        # 2 billing + 1 marketplace = 3
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_service_filter_empty(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client, services=["nonexistent"])
        tools = toolkit.get_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_tool_names_match_catalog(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        toolkit = await A2AToolkit.from_client(mock_client)
        names = {t.name for t in toolkit.get_tools()}
        assert names == {"get_balance", "deposit", "create_intent", "search_services"}


class TestToolkitWithToolPricing:
    """Toolkit must work when pricing() returns ToolPricing dataclass instances."""

    @pytest.mark.asyncio
    async def test_from_client_with_toolpricing_objects(self, mock_client):
        from a2a_crewai.toolkit import A2AToolkit

        from sdk.src.a2a_client.models import ToolPricing

        catalog = [
            ToolPricing(
                name="get_balance",
                service="billing",
                description="Get balance",
                pricing={"cost": 0},
                tier_required="free",
                input_schema={
                    "type": "object",
                    "properties": {"agent_id": {"type": "string", "description": "ID"}},
                    "required": ["agent_id"],
                },
            ),
            ToolPricing(
                name="deposit",
                service="billing",
                description="Deposit",
                pricing={"cost": 0},
                tier_required="free",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string", "description": "ID"},
                        "amount": {"type": "number", "description": "Amount"},
                    },
                    "required": ["agent_id", "amount"],
                },
            ),
        ]
        mock_client.pricing.return_value = catalog
        toolkit = await A2AToolkit.from_client(mock_client)
        tools = toolkit.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"get_balance", "deposit"}
