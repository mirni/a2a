"""TDD RED: Tests for toolkit.py — A2AToolkit."""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool, BaseToolkit


class TestA2AToolkit:
    def test_is_base_toolkit(self):
        from a2a_langchain.toolkit import A2AToolkit
        assert issubclass(A2AToolkit, BaseToolkit)

    @pytest.mark.asyncio
    async def test_from_client_creates_toolkit(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client)
        assert isinstance(toolkit, A2AToolkit)

    @pytest.mark.asyncio
    async def test_get_tools_returns_list(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client)
        tools = toolkit.get_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_tools_are_base_tool_instances(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client)
        for tool in toolkit.get_tools():
            assert isinstance(tool, BaseTool)

    @pytest.mark.asyncio
    async def test_tool_count_matches_catalog(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client)
        tools = toolkit.get_tools()
        # Sample catalog has 4 tools
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_calls_pricing(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        await A2AToolkit.from_client(mock_client)
        mock_client.pricing.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_filter(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client, services=["billing"])
        tools = toolkit.get_tools()
        # Sample catalog has 2 billing tools: get_balance, deposit
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"get_balance", "deposit"}

    @pytest.mark.asyncio
    async def test_service_filter_multiple(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(
            mock_client, services=["billing", "marketplace"]
        )
        tools = toolkit.get_tools()
        # 2 billing + 1 marketplace = 3
        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_service_filter_empty(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(
            mock_client, services=["nonexistent"]
        )
        tools = toolkit.get_tools()
        assert len(tools) == 0

    @pytest.mark.asyncio
    async def test_tool_names_match_catalog(self, mock_client):
        from a2a_langchain.toolkit import A2AToolkit
        toolkit = await A2AToolkit.from_client(mock_client)
        names = {t.name for t in toolkit.get_tools()}
        assert names == {"get_balance", "deposit", "create_intent", "search_services"}
