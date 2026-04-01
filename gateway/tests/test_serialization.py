"""Tests for T7 (string-serialized Decimals) and T8 (ISO 8601 timestamps)."""

from __future__ import annotations

import pytest

from gateway.src.serialization import serialize_money, serialize_response, serialize_timestamp

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for serialize_money
# ---------------------------------------------------------------------------


class TestSerializeMoney:
    def test_int_value(self):
        assert serialize_money(100) == "100.00"

    def test_float_value(self):
        assert serialize_money(1.5) == "1.50"

    def test_float_precision(self):
        """0.1 + 0.2 should not produce 0.30000000000000004."""
        assert serialize_money(0.1 + 0.2) == "0.30"

    def test_already_string_passthrough(self):
        assert serialize_money("42.00") == "42.00"

    def test_zero(self):
        assert serialize_money(0) == "0.00"

    def test_large_value(self):
        assert serialize_money(1000000.99) == "1000000.99"


# ---------------------------------------------------------------------------
# Unit tests for serialize_timestamp
# ---------------------------------------------------------------------------


class TestSerializeTimestamp:
    def test_unix_timestamp_int(self):
        result = serialize_timestamp(0)
        assert "1970" in result
        assert "T" in result

    def test_unix_timestamp_float(self):
        result = serialize_timestamp(1711929600.0)
        assert "T" in result

    def test_iso8601_passthrough(self):
        iso = "2024-04-01T00:00:00+00:00"
        assert serialize_timestamp(iso) == iso

    def test_numeric_string_converted(self):
        result = serialize_timestamp("0")
        assert "1970" in result

    def test_non_numeric_string_passthrough(self):
        result = serialize_timestamp("not-a-timestamp")
        assert result == "not-a-timestamp"


# ---------------------------------------------------------------------------
# Unit tests for serialize_response
# ---------------------------------------------------------------------------


class TestSerializeResponse:
    def test_nested_dict(self):
        data = {"user": {"balance": 50}}
        result = serialize_response(data)
        assert result["user"]["balance"] == "50.00"

    def test_list_of_dicts(self):
        data = [{"balance": 10}, {"balance": 20}]
        result = serialize_response(data)
        assert result[0]["balance"] == "10.00"
        assert result[1]["balance"] == "20.00"

    def test_non_monetary_field_untouched(self):
        data = {"name": "test", "count": 5}
        result = serialize_response(data)
        assert result["name"] == "test"
        assert result["count"] == 5

    def test_none_monetary_field_untouched(self):
        """None in monetary field should pass through (not serialized)."""
        data = {"balance": None}
        result = serialize_response(data)
        assert result["balance"] is None

    def test_none_timestamp_skipped(self):
        data = {"created_at": None}
        result = serialize_response(data)
        assert result["created_at"] is None

    def test_scalar_passthrough(self):
        assert serialize_response("hello") == "hello"
        assert serialize_response(42) == 42
        assert serialize_response(None) is None


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
