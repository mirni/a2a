"""Tests for P3-4 (tool name sanitization) and P3-5 (extra field rejection)."""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# P3-4: Tool name sanitization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_tool_name_truncated_in_error(client, api_key):
    """Tool names longer than 128 chars should be truncated in error messages."""
    long_name = "x" * 300
    resp = await client.post(
        "/v1/execute",
        json={"tool": long_name, "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Should still get an error (unknown tool), but the name in the message
    # must be truncated to at most 128 chars.
    body = resp.json()
    detail = body["detail"]
    # The tool name embedded in the detail must not exceed 128 chars.
    # The error format is "Unknown tool: <name>" so we check that the full
    # 300-char name does NOT appear.
    assert long_name not in detail
    assert len(detail) <= 256  # generous upper bound for the full message


@pytest.mark.asyncio
async def test_null_bytes_stripped_from_tool_name(client, api_key):
    """Null bytes in tool names must be stripped before any processing."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get\x00_balance", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    body = resp.json()
    detail = body["detail"]
    # Null bytes must not appear in the detail message
    assert "\x00" not in detail


@pytest.mark.asyncio
async def test_null_bytes_only_tool_name_treated_as_missing(client, api_key):
    """A tool name consisting entirely of null bytes becomes empty after stripping."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "\x00\x00\x00", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # After stripping null bytes, the tool name is empty → 400 missing tool
    assert resp.status_code == 400
    assert resp.json()["type"].endswith("/bad-request")


# ---------------------------------------------------------------------------
# P3-5: Extra field rejection (extra="forbid")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_fields_rejected_with_422(client, api_key):
    """Sending extra fields in the request body must return 422."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}, "evil": "payload"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_multiple_extra_fields_rejected(client, api_key):
    """Multiple extra fields should all be rejected."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_balance",
            "params": {"agent_id": "test-agent"},
            "foo": 1,
            "bar": 2,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_valid_request_still_works(client, api_key):
    """A valid request with only 'tool' and 'params' must succeed."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_valid_request_without_params_defaults(client, api_key):
    """Omitting 'params' should default to empty dict (existing behavior)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # get_balance requires agent_id, so missing param → 400
    # But the point is it should NOT be 422 — the body structure is valid.
    assert resp.status_code == 400
    assert resp.json()["type"].endswith("/missing-parameter")
