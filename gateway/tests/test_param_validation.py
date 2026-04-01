"""Tests for parameter validation on /v1/execute (BUG-1 fix)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_missing_required_param_returns_400(client, api_key):
    """Missing a required param should return 400, not 500."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"].endswith("/missing-parameter")
    assert "agent_id" in body["detail"]


async def test_missing_multiple_required_params(client, api_key):
    """Multiple missing params listed in error message."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "send_message", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"].endswith("/missing-parameter")
    assert "sender" in body["detail"]


async def test_valid_params_pass_validation(client, api_key):
    """Providing all required params should not trigger validation error."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


async def test_tool_with_no_required_params(client, admin_api_key):
    """Tools without required params should work with empty params."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "list_backups", "params": {}},
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200


async def test_metrics_record_after_requests(client, api_key):
    """Metrics should be non-zero after tool execution (BUG-2 fix)."""
    # Make a request first
    await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Check metrics
    resp = await client.get("/v1/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "a2a_requests_total" in text
    # Should have at least 1 request recorded
    for line in text.split("\n"):
        if line.startswith("a2a_requests_total "):
            count = int(line.split()[-1])
            assert count >= 1, f"Expected requests_total >= 1, got {count}"
            break


# ---------------------------------------------------------------------------
# Type validation: gateway rejects wrong types before dispatch
# ---------------------------------------------------------------------------


async def test_rejects_string_for_number_field(client, api_key):
    """Sending a string where a number is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "deposit",
            "params": {"agent_id": "test-agent", "amount": "not-a-number"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "amount" in body["detail"].lower()


async def test_rejects_string_for_integer_field(client, api_key):
    """Sending a string where an integer is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_transactions",
            "params": {"agent_id": "test-agent", "limit": "ten"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_extra_params_are_allowed(client, api_key):
    """Extra params not in schema are allowed (catalog may be incomplete)."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_balance",
            "params": {
                "agent_id": "test-agent",
                "extra_field": "ignored",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Extra fields are NOT rejected — they pass through to the tool
    assert resp.status_code == 200


async def test_rejects_number_for_string_field(client, api_key):
    """Sending a number where a string is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": 12345}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_rejects_boolean_for_string_field(client, api_key):
    """Sending a boolean where a string is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": True}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_rejects_array_for_string_field(client, api_key):
    """Sending an array where a string is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": ["test-agent"]}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_rejects_null_for_required_string(client, api_key):
    """Sending null for a required string param should return 400 or 422."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": None}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (400, 422)


async def test_rejects_float_for_integer_field(client, api_key):
    """Sending a float where an integer is expected should return 422."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_transactions",
            "params": {"agent_id": "test-agent", "limit": 10.5},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


async def test_accepts_valid_optional_params(client, api_key):
    """Valid optional params with correct types should be accepted."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_balance",
            "params": {"agent_id": "test-agent", "currency": "CREDITS"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code != 422


async def test_accepts_integer_for_number_field(client, api_key):
    """Integer values should be accepted for number fields (JSON compat)."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "deposit",
            "params": {"agent_id": "test-agent", "amount": 100},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code != 422
