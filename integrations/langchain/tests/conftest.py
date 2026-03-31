"""Shared fixtures for a2a-langchain tests."""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

# Ensure project roots are importable
_repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
_integration_src = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
for p in (_repo_root, _integration_src):
    if p not in sys.path:
        sys.path.insert(0, p)

from sdk.src.a2a_client import A2AClient
from sdk.src.a2a_client.models import ExecuteResponse


def _make_exec_response(result: dict) -> ExecuteResponse:
    """Build a fake ExecuteResponse."""
    return ExecuteResponse(success=True, result=result, charged=0.0)


SAMPLE_CATALOG = [
    {
        "tool": "get_balance",
        "service": "billing",
        "description": "Get wallet balance for an agent",
        "cost": 0,
        "tier": "free",
        "schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "tool": "deposit",
        "service": "billing",
        "description": "Deposit credits into agent wallet",
        "cost": 0,
        "tier": "free",
        "schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The agent ID"},
                "amount": {"type": "number", "description": "Amount to deposit"},
            },
            "required": ["agent_id", "amount"],
        },
    },
    {
        "tool": "create_intent",
        "service": "payments",
        "description": "Create a payment intent",
        "cost": 0.5,
        "tier": "free",
        "schema": {
            "type": "object",
            "properties": {
                "payer": {"type": "string", "description": "Payer agent ID"},
                "payee": {"type": "string", "description": "Payee agent ID"},
                "amount": {"type": "number", "description": "Payment amount"},
            },
            "required": ["payer", "payee", "amount"],
        },
    },
    {
        "tool": "search_services",
        "service": "marketplace",
        "description": "Search for services in the marketplace",
        "cost": 0,
        "tier": "free",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
]


@pytest.fixture
def mock_client():
    """A2AClient with mocked execute() and pricing() for unit testing."""
    client = A2AClient.__new__(A2AClient)
    client.base_url = "http://test"
    client.api_key = "test-key"
    client.max_retries = 0
    client.retry_base_delay = 0.0
    client.pricing_cache_ttl = 300.0
    client._pricing_cache = None
    client._pricing_cache_time = 0.0
    client._client = None
    client.execute = AsyncMock(
        return_value=_make_exec_response({"balance": "100.00"})
    )
    client.pricing = AsyncMock(return_value=SAMPLE_CATALOG)
    return client


@pytest.fixture
def sample_catalog():
    """The sample tool catalog used in tests."""
    return SAMPLE_CATALOG
