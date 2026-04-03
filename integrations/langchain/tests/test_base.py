"""TDD RED: Tests for _base.py — A2ABaseTool and create_tool factory."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool, ToolException

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


class TestCreateToolWithToolPricingShape:
    """create_tool must work with ToolPricing-shaped dicts (name/input_schema keys)."""

    def test_accepts_name_key(self, mock_client):
        from a2a_langchain._base import create_tool

        tool_def = {
            "name": "get_balance",
            "service": "billing",
            "description": "Get wallet balance",
            "input_schema": {
                "type": "object",
                "properties": {"agent_id": {"type": "string", "description": "Agent ID"}},
                "required": ["agent_id"],
            },
        }
        tool = create_tool(mock_client, tool_def)
        assert tool.name == "get_balance"

    def test_schema_from_input_schema_key(self, mock_client):
        from a2a_langchain._base import create_tool

        tool_def = {
            "name": "deposit",
            "service": "billing",
            "description": "Deposit credits",
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent"},
                    "amount": {"type": "number", "description": "Amount"},
                },
                "required": ["agent_id", "amount"],
            },
        }
        tool = create_tool(mock_client, tool_def)
        field_names = set(tool.args_schema.model_fields.keys())
        assert "agent_id" in field_names
        assert "amount" in field_names

    @pytest.mark.asyncio
    async def test_execute_with_tool_pricing_shape(self, mock_client):
        from a2a_langchain._base import create_tool

        mock_client.execute.return_value = _make_exec_response({"balance": "50.00"})
        tool_def = {
            "name": "get_balance",
            "service": "billing",
            "description": "Get balance",
            "input_schema": {
                "type": "object",
                "properties": {"agent_id": {"type": "string", "description": "ID"}},
                "required": ["agent_id"],
            },
        }
        tool = create_tool(mock_client, tool_def)
        await tool.arun({"agent_id": "a1"})
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "a1"})


class TestErrorHandling:
    """A2AError from client.execute should be wrapped as ToolException."""

    @pytest.mark.asyncio
    async def test_a2a_error_becomes_tool_exception(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        from sdk.src.a2a_client.errors import A2AError

        mock_client.execute = AsyncMock(side_effect=A2AError("boom", code="error", status=500))
        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        with pytest.raises(ToolException, match="boom"):
            await tool._arun(agent_id="a1")

    @pytest.mark.asyncio
    async def test_auth_error_becomes_tool_exception(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        from sdk.src.a2a_client.errors import AuthenticationError

        mock_client.execute = AsyncMock(side_effect=AuthenticationError("bad key", code="auth_error", status=401))
        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        with pytest.raises(ToolException, match="bad key"):
            await tool._arun(agent_id="a1")

    @pytest.mark.asyncio
    async def test_rate_limit_error_becomes_tool_exception(self, mock_client):
        from a2a_langchain._base import A2ABaseTool

        from sdk.src.a2a_client.errors import RateLimitError

        mock_client.execute = AsyncMock(side_effect=RateLimitError("slow down", code="rate_limit", status=429))
        tool = A2ABaseTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        with pytest.raises(ToolException, match="slow down"):
            await tool._arun(agent_id="a1")

    @pytest.mark.asyncio
    async def test_create_tool_error_handling(self, mock_client):
        from a2a_langchain._base import create_tool

        from sdk.src.a2a_client.errors import A2AError

        mock_client.execute = AsyncMock(side_effect=A2AError("fail", code="error", status=500))
        tool_def = {
            "name": "get_balance",
            "service": "billing",
            "description": "Get balance",
            "input_schema": {
                "type": "object",
                "properties": {"agent_id": {"type": "string", "description": "ID"}},
                "required": ["agent_id"],
            },
        }
        tool = create_tool(mock_client, tool_def)
        with pytest.raises(ToolException, match="fail"):
            await tool.ainvoke({"agent_id": "a1"})
