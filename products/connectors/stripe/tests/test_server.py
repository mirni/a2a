"""Tests for MCP server tool registration and validation."""

import json

import pytest
from src.models import ToolResult
from src.server import (
    _result_to_json,
    _validation_error_result,
    mcp,
)


class TestResultHelpers:
    def test_result_to_json(self):
        r = ToolResult(success=True, data={"id": "cus_1"})
        raw = _result_to_json(r)
        parsed = json.loads(raw)
        assert parsed["success"] is True
        assert parsed["data"]["id"] == "cus_1"

    def test_validation_error_result(self):
        from pydantic import ValidationError as PydanticValidationError
        from src.models import CreatePaymentIntentInput

        with pytest.raises(PydanticValidationError) as exc_info:
            CreatePaymentIntentInput(amount=-1, currency="x", idempotency_key="k")
        raw = _validation_error_result(exc_info.value)
        parsed = json.loads(raw)
        assert parsed["success"] is False
        assert parsed["error"]["code"] == "VALIDATION_ERROR"
        assert "validation_errors" in parsed["error"]["details"]


class TestMCPServerRegistration:
    """Verify all tools are registered on the FastMCP server."""

    def test_server_name(self):
        assert mcp.name == "stripe-connector"

    def test_all_tools_registered(self):
        """Check that all 7 tools exist."""
        tool_names = set()
        # Access internal tool manager
        for name in mcp._tool_manager._tools:
            tool_names.add(name)

        expected = {
            "create_customer",
            "create_payment_intent",
            "list_charges",
            "create_subscription",
            "get_balance",
            "create_refund",
            "list_invoices",
        }
        assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
