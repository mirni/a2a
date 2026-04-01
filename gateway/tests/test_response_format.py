"""Tests for envelope-free response format (T3).

Success responses must:
- Return the tool result directly as the body (no wrapper)
- NOT contain success, result, charged, request_id fields
- Have X-Charged header with cost value
- Have X-Request-ID header
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_success_body_is_result_directly(client, api_key):
    """Success response body IS the tool result, not wrapped in envelope."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Direct result — balance at top level
    assert "balance" in data
    # No envelope fields
    assert "success" not in data
    assert "result" not in data
    assert "charged" not in data
    assert "request_id" not in data


async def test_x_charged_header_present(client, api_key):
    """X-Charged header must be present with the cost value."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-charged" in resp.headers
    charged = resp.headers["x-charged"]
    # Must be a parseable number
    float(charged)


async def test_x_request_id_header_on_success(client, api_key):
    """X-Request-ID header must be present on success responses."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers


async def test_register_returns_unwrapped(client, app):
    """POST /v1/register returns agent data directly, not wrapped."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "new-test-agent"},
    )
    data = resp.json()
    assert "agent_id" in data
    assert "api_key" in data
    assert "success" not in data
    assert "result" not in data


async def test_create_tool_returns_201(client, api_key, app):
    """Create tools (e.g. create_intent) should return 201 Created."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-201", initial_balance=0.0, signup_bonus=False)
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "payee-201",
                "amount": 10.0,
                "description": "test 201",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201
    assert "location" in resp.headers


async def test_non_create_tool_returns_200(client, api_key):
    """Non-create tools (e.g. get_balance) should still return 200."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


async def test_register_returns_201(client, app):
    """POST /v1/register should return 201 Created."""
    resp = await client.post(
        "/v1/register",
        json={"agent_id": "agent-201-test"},
    )
    assert resp.status_code == 201
