"""TDD RED: Tests for _base.py — A2ACrewTool and create_tool factory."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from crewai.tools import BaseTool

from tests.conftest import _make_exec_response


class TestA2ACrewTool:
    def test_is_subclass_of_base_tool(self):
        from a2a_crewai._base import A2ACrewTool

        assert issubclass(A2ACrewTool, BaseTool)

    def test_has_client_attribute(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        tool = A2ACrewTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get wallet balance",
        )
        assert tool.client is mock_client
        assert tool.tool_name == "get_balance"

    def test_run_calls_execute(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        mock_client.execute.return_value = _make_exec_response({"balance": "100.00"})
        tool = A2ACrewTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get wallet balance",
        )
        result = tool._run(agent_id="a1")
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "a1"})
        parsed = json.loads(result)
        assert parsed["balance"] == "100.00"

    def test_run_returns_json_string(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        mock_client.execute.return_value = _make_exec_response({"ok": True})
        tool = A2ACrewTool(
            client=mock_client,
            tool_name="test_tool",
            name="test_tool",
            description="Test",
        )
        result = tool._run(key="value")
        assert isinstance(result, str)
        json.loads(result)  # should not raise


class TestCreateTool:
    def test_returns_base_tool(self, mock_client, sample_catalog):
        from a2a_crewai._base import create_tool

        tool = create_tool(mock_client, sample_catalog[0])
        assert isinstance(tool, BaseTool)

    def test_name_matches_catalog(self, mock_client, sample_catalog):
        from a2a_crewai._base import create_tool

        tool = create_tool(mock_client, sample_catalog[0])
        assert tool.name == "get_balance"

    def test_description_contains_catalog_text(self, mock_client, sample_catalog):
        from a2a_crewai._base import create_tool

        tool = create_tool(mock_client, sample_catalog[0])
        assert "Get wallet balance for an agent" in tool.description

    def test_schema_fields_match_catalog(self, mock_client, sample_catalog):
        from a2a_crewai._base import create_tool

        tool = create_tool(mock_client, sample_catalog[1])  # deposit
        schema = tool.args_schema
        field_names = set(schema.model_fields.keys())
        assert "agent_id" in field_names
        assert "amount" in field_names

    def test_run_delegates_to_execute(self, mock_client, sample_catalog):
        from a2a_crewai._base import create_tool

        mock_client.execute.return_value = _make_exec_response({"balance": "50.00"})
        tool = create_tool(mock_client, sample_catalog[0])
        tool._run(agent_id="a1")
        mock_client.execute.assert_called_once_with("get_balance", {"agent_id": "a1"})


class TestCreateToolWithToolPricingShape:
    """create_tool must work with ToolPricing dataclass instances."""

    def test_accepts_toolpricing_dataclass(self, mock_client):
        from a2a_crewai._base import create_tool

        from sdk.src.a2a_client.models import ToolPricing

        tp = ToolPricing(
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
        )
        tool = create_tool(mock_client, tp)
        assert tool.name == "get_balance"

    def test_schema_from_dataclass(self, mock_client):
        from a2a_crewai._base import create_tool

        from sdk.src.a2a_client.models import ToolPricing

        tp = ToolPricing(
            name="deposit",
            service="billing",
            description="Deposit",
            pricing={},
            tier_required="free",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "ID"},
                    "amount": {"type": "number", "description": "Amount"},
                },
                "required": ["agent_id", "amount"],
            },
        )
        tool = create_tool(mock_client, tp)
        field_names = set(tool.args_schema.model_fields.keys())
        assert "agent_id" in field_names
        assert "amount" in field_names


class TestErrorHandling:
    """A2AError from client.execute should return error JSON (CrewAI pattern)."""

    def test_a2a_error_returns_error_json(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        from sdk.src.a2a_client.errors import A2AError

        mock_client.execute = AsyncMock(side_effect=A2AError("boom", code="error", status=500))
        tool = A2ACrewTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        result = tool._run(agent_id="a1")
        parsed = json.loads(result)
        assert parsed["error"] is True
        assert "boom" in parsed["message"]

    def test_auth_error_returns_error_json(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        from sdk.src.a2a_client.errors import AuthenticationError

        mock_client.execute = AsyncMock(side_effect=AuthenticationError("bad key", code="auth_error", status=401))
        tool = A2ACrewTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        result = tool._run(agent_id="a1")
        parsed = json.loads(result)
        assert parsed["error"] is True
        assert parsed["code"] == "auth_error"

    def test_rate_limit_error_returns_error_json(self, mock_client):
        from a2a_crewai._base import A2ACrewTool

        from sdk.src.a2a_client.errors import RateLimitError

        mock_client.execute = AsyncMock(side_effect=RateLimitError("slow down", code="rate_limit", status=429))
        tool = A2ACrewTool(
            client=mock_client,
            tool_name="get_balance",
            name="get_balance",
            description="Get balance",
        )
        result = tool._run(agent_id="a1")
        parsed = json.loads(result)
        assert parsed["error"] is True
        assert parsed["status"] == 429

    def test_create_tool_error_handling(self, mock_client):
        from a2a_crewai._base import create_tool

        from sdk.src.a2a_client.errors import A2AError

        mock_client.execute = AsyncMock(side_effect=A2AError("fail", code="error", status=500))
        tool = create_tool(
            mock_client,
            {
                "name": "get_balance",
                "service": "billing",
                "description": "Get balance",
                "input_schema": {
                    "type": "object",
                    "properties": {"agent_id": {"type": "string", "description": "ID"}},
                    "required": ["agent_id"],
                },
            },
        )
        result = tool._run(agent_id="a1")
        parsed = json.loads(result)
        assert parsed["error"] is True
