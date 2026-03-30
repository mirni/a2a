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
    assert body["success"] is False
    assert body["error"]["code"] == "missing_parameter"
    assert "agent_id" in body["error"]["message"]


async def test_missing_multiple_required_params(client, api_key):
    """Multiple missing params listed in error message."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "send_message", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "missing_parameter"
    assert "sender" in body["error"]["message"]


async def test_valid_params_pass_validation(client, api_key):
    """Providing all required params should not trigger validation error."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


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
