"""TDD RED: Tests for _base.py — A2ABaseTool and create_tool factory."""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import BaseTool

from tests.conftest import _make_exec_response


class TestA2ABaseTool:
    def test_is_subclass_of_base_tool(self):
        from a2a_langchain._base import A2ABaseTool

        assert issubclass(A2ABaseTool, BaseTool)

    def test_has_client_attribute(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get wallet balance",
        )
        assert tool.client is mock_client
        assert tool.tool_name == "get_balance"

    @pytest.mark.asyncio
    async def test_arun_calls_execute(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        mock_client.execute.return_value = _make_exec_response({"balance": "100.00"})
        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get wallet balance",
        )
        result = await tool._arun(agent_id="agent-1")
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "agent-1"})
        parsed = json.loads(result)
        assert parsed["balance"] == "100.00"

    def test_run_calls_execute_sync(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        mock_client.execute.return_value = _make_exec_response({"balance": "100.00"})
        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get wallet balance",
        )
        result = tool._run(agent_id="agent-1")
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["balance"] == "100.00"


class TestCreateTool:
    def test_returns_base_tool(self, mock_client, sample_catalog):
        from a2a_langchain._base import create_tool

        tool_def = sample_catalog[0]  # get_balance
        tool = create_tool(mock_client, tool_def)
        assert isinstance(tool, BaseTool)

    def test_name_matches_catalog(self, mock_client, sample_catalog):
        from a2a_langchain._base import create_tool

        tool_def = sample_catalog[0]
        tool = create_tool(mock_client, tool_def)
        assert tool.name == "get_balance"

    def test_description_matches_catalog(self, mock_client, sample_catalog):
        from a2a_langchain._base import create_tool

        tool_def = sample_catalog[0]
        tool = create_tool(mock_client, tool_def)
        assert tool.description == "Get wallet balance for an agent"

    def test_schema_fields_match_catalog(self, mock_client, sample_catalog):
        from a2a_langchain._base import create_tool

        tool_def = sample_catalog[1]  # deposit — has agent_id + amount
        tool = create_tool(mock_client, tool_def)
        schema = tool.args_schema
        field_names = set(schema.model_fields.keys())
        assert "agent_id" in field_names
        assert "amount" in field_names

    @pytest.mark.asyncio
    async def test_arun_delegates_to_execute(self, mock_client, sample_catalog):
        from a2a_langchain._base import create_tool

        mock_client.execute.return_value = _make_exec_response({"balance": "50.00"})
        tool = create_tool(mock_client, sample_catalog[0])
        await tool.arun({"agent_id": "a1"})
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "a1"})
