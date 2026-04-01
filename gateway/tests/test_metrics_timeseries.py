"""Tests for P2-12: Metrics Time-Series tool (get_metrics_timeseries)."""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.asyncio


class TestMetricsTimeseries:
    """Tests for the get_metrics_timeseries tool."""

    async def test_tool_exists_in_catalog(self, client, api_key):
        """The tool should be registered in the catalog and executable."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_metrics_timeseries", "params": {"agent_id": "test-agent", "interval": "hour"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should not return unknown_tool
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool", "Tool must exist in catalog"

    async def test_returns_buckets_for_hourly_interval(self, client, api_key, app):
        """Should return bucketed usage data with hourly interval."""
        ctx = app.state.ctx
        # Record some usage
        time.time()
        await ctx.tracker.storage.record_usage("test-agent", "get_balance", 0.1)
        await ctx.tracker.storage.record_usage("test-agent", "get_balance", 0.2)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_metrics_timeseries",
                "params": {"agent_id": "test-agent", "interval": "hour"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "buckets" in result
        assert isinstance(result["buckets"], list)
        # Should have at least one bucket with calls and cost
        assert len(result["buckets"]) >= 1
        bucket = result["buckets"][0]
        assert "timestamp" in bucket
        assert "calls" in bucket
        assert "cost" in bucket
        assert bucket["calls"] >= 2
        assert float(bucket["cost"]) >= 0.3 - 0.01  # floating point tolerance

    async def test_returns_buckets_for_daily_interval(self, client, api_key, app):
        """Should return bucketed usage data with daily interval."""
        ctx = app.state.ctx
        await ctx.tracker.storage.record_usage("test-agent", "deposit", 1.0)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_metrics_timeseries",
                "params": {"agent_id": "test-agent", "interval": "day"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert "buckets" in result
        assert len(result["buckets"]) >= 1

    async def test_since_filters_old_records(self, client, api_key, app):
        """The since parameter should filter out records before the timestamp."""
        ctx = app.state.ctx
        await ctx.tracker.storage.record_usage("test-agent", "deposit", 0.5)

        future_ts = time.time() + 86400  # 1 day from now
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_metrics_timeseries",
                "params": {
                    "agent_id": "test-agent",
                    "interval": "hour",
                    "since": future_ts,
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # No buckets should match a future since timestamp
        assert len(data["buckets"]) == 0

    async def test_limit_constrains_bucket_count(self, client, api_key, app):
        """The limit parameter should constrain the number of returned buckets."""
        ctx = app.state.ctx
        await ctx.tracker.storage.record_usage("test-agent", "deposit", 0.1)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_metrics_timeseries",
                "params": {
                    "agent_id": "test-agent",
                    "interval": "hour",
                    "limit": 2,
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["buckets"]) <= 2

    async def test_empty_agent_returns_empty_buckets(self, client, api_key):
        """An agent with no usage records should get empty buckets."""
        # Use test-agent (matches api_key) with future since to get empty results
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_metrics_timeseries",
                "params": {"agent_id": "test-agent", "interval": "hour", "since": time.time() + 86400 * 365},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["buckets"] == []

    async def test_missing_required_params(self, client, api_key):
        """Should fail when required params (agent_id, interval) are missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_metrics_timeseries", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
