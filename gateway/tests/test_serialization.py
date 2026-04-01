"""Tests for T7 (string-serialized Decimals) and T8 (ISO 8601 timestamps)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_monetary_values_are_strings(client, api_key):
    """Monetary fields (balance, amount, cost) should be string-serialized."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["balance"], str), f"balance should be string, got {type(data['balance'])}"


async def test_x_charged_header_is_decimal_string(client, api_key):
    """X-Charged header should be a 2-decimal fixed-point string."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    charged = resp.headers["x-charged"]
    assert "." in charged, "X-Charged should be decimal string like '0.00'"
    # Should have exactly 2 decimal places
    parts = charged.split(".")
    assert len(parts[1]) == 2


async def test_timestamps_are_iso8601(client, api_key, app):
    """Timestamp fields should be ISO 8601 format."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("ts-payee", initial_balance=0.0, signup_bonus=False)
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {
                "payer": "test-agent",
                "payee": "ts-payee",
                "amount": 5.0,
                "description": "timestamp test",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    # created_at should be ISO 8601 string like "2026-04-01T00:00:00+00:00"
    if "created_at" in data:
        ts = data["created_at"]
        assert isinstance(ts, str), f"created_at should be string, got {type(ts)}"
        assert "T" in ts, f"created_at should be ISO 8601, got {ts}"
