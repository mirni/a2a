"""Tests for integration package generator (TDD).

Generates LangChain and CrewAI integration code from the tool catalog.
"""

from __future__ import annotations

import json

import pytest


class TestCatalogLoader:
    """Test loading and parsing the tool catalog."""

    def test_load_catalog(self):
        from gateway.src.integration_generator import load_catalog

        tools = load_catalog()
        assert len(tools) > 0
        assert all("name" in t for t in tools)

    def test_catalog_tool_has_required_fields(self):
        from gateway.src.integration_generator import load_catalog

        tools = load_catalog()
        tool = tools[0]
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool

    def test_filter_by_service(self):
        from gateway.src.integration_generator import load_catalog

        tools = load_catalog(service="billing")
        assert len(tools) > 0
        assert all(t["service"] == "billing" for t in tools)


class TestLangChainGenerator:
    """Test LangChain tool wrapper generation."""

    def test_generate_single_tool(self):
        from gateway.src.integration_generator import generate_langchain_tool

        tool_def = {
            "name": "get_balance",
            "description": "Get the current wallet balance for an agent.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "The agent identifier"},
                },
                "required": ["agent_id"],
            },
        }
        code = generate_langchain_tool(tool_def)
        assert "class GetBalanceInput" in code
        assert "agent_id: str" in code
        assert "get_balance" in code
        assert "StructuredTool" in code

    def test_generate_tool_with_optional_params(self):
        from gateway.src.integration_generator import generate_langchain_tool

        tool_def = {
            "name": "search_services",
            "description": "Search for services.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        }
        code = generate_langchain_tool(tool_def)
        assert "query: str" in code
        assert "Optional[int]" in code or "int | None" in code

    def test_generate_full_module(self):
        from gateway.src.integration_generator import generate_langchain_module

        tools = [
            {
                "name": "get_balance",
                "service": "billing",
                "description": "Get balance.",
                "input_schema": {
                    "type": "object",
                    "properties": {"agent_id": {"type": "string"}},
                    "required": ["agent_id"],
                },
            },
            {
                "name": "deposit",
                "service": "billing",
                "description": "Deposit funds.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                    "required": ["agent_id", "amount"],
                },
            },
        ]
        code = generate_langchain_module(tools)
        assert "from langchain.tools import StructuredTool" in code
        assert "GetBalanceInput" in code
        assert "DepositInput" in code
        assert "A2A_TOOLS" in code

    def test_generated_module_has_imports(self):
        from gateway.src.integration_generator import generate_langchain_module

        code = generate_langchain_module([{
            "name": "test_tool",
            "service": "test",
            "description": "A test.",
            "input_schema": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        }])
        assert "import" in code
        assert "httpx" in code or "requests" in code


class TestCrewAIGenerator:
    """Test CrewAI tool wrapper generation."""

    def test_generate_single_tool(self):
        from gateway.src.integration_generator import generate_crewai_tool

        tool_def = {
            "name": "get_balance",
            "description": "Get the current wallet balance for an agent.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "The agent identifier"},
                },
                "required": ["agent_id"],
            },
        }
        code = generate_crewai_tool(tool_def)
        assert "class GetBalanceTool" in code
        assert "BaseTool" in code
        assert "get_balance" in code

    def test_generate_full_module(self):
        from gateway.src.integration_generator import generate_crewai_module

        tools = [{
            "name": "get_balance",
            "service": "billing",
            "description": "Get balance.",
            "input_schema": {
                "type": "object",
                "properties": {"agent_id": {"type": "string"}},
                "required": ["agent_id"],
            },
        }]
        code = generate_crewai_module(tools)
        assert "from crewai.tools import BaseTool" in code
        assert "GetBalanceTool" in code
        assert "A2A_TOOLS" in code


class TestSchemaToType:
    """Test JSON Schema type to Python type conversion."""

    def test_string_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "string"}) == "str"

    def test_number_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "number"}) == "float"

    def test_integer_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "integer"}) == "int"

    def test_boolean_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "boolean"}) == "bool"

    def test_array_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "array", "items": {"type": "string"}}) == "list[str]"

    def test_object_type(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({"type": "object"}) == "dict"

    def test_unknown_defaults_to_any(self):
        from gateway.src.integration_generator import schema_to_python_type

        assert schema_to_python_type({}) == "Any"


class TestToolNameConversion:
    """Test snake_case to PascalCase conversion."""

    def test_simple(self):
        from gateway.src.integration_generator import to_class_name

        assert to_class_name("get_balance") == "GetBalance"

    def test_multi_word(self):
        from gateway.src.integration_generator import to_class_name

        assert to_class_name("search_agents_by_metrics") == "SearchAgentsByMetrics"

    def test_single_word(self):
        from gateway.src.integration_generator import to_class_name

        assert to_class_name("deposit") == "Deposit"
