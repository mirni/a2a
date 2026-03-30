"""Tests for time-series metric storage (PRD 010).

Covers: store, query range, latest, upsert aggregates, leaderboard, unique constraint.
"""

from __future__ import annotations

import time

import pytest


class TestStoreTimeseries:
    @pytest.mark.asyncio
    async def test_store_and_query_single(self, storage):
        """Store a single metric and retrieve it via range query."""
        now = time.time()
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            value=2.35,
            timestamp=now,
            data_source="self_reported",
        )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d")
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "bot-1"
        assert rows[0]["metric_name"] == "sharpe_30d"
        assert rows[0]["value"] == pytest.approx(2.35)
        assert rows[0]["data_source"] == "self_reported"

    @pytest.mark.asyncio
    async def test_store_with_commitment_hash(self, storage):
        """Commitment hash is optional and stored when provided."""
        now = time.time()
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="pnl_30d",
            value=1500.0,
            timestamp=now,
            data_source="exchange_api",
            commitment_hash="abc123",
        )
        rows = await storage.query_timeseries("bot-1", "pnl_30d")
        assert rows[0]["commitment_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_store_default_window_days(self, storage):
        """Default window_days is 30."""
        now = time.time()
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            value=1.0,
            timestamp=now,
            data_source="self_reported",
        )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d")
        assert rows[0]["window_days"] == 30

    @pytest.mark.asyncio
    async def test_store_custom_window_days(self, storage):
        """Custom window_days is stored correctly."""
        now = time.time()
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            value=1.0,
            timestamp=now,
            data_source="self_reported",
            window_days=7,
        )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d")
        assert rows[0]["window_days"] == 7


class TestQueryTimeseries:
    @pytest.mark.asyncio
    async def test_range_query_with_since(self, storage):
        """Only rows after 'since' are returned."""
        base = time.time() - 100
        for i in range(5):
            await storage.store_timeseries(
                agent_id="bot-1",
                metric_name="sharpe_30d",
                value=float(i),
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d", since=base + 25)
        assert len(rows) == 2  # timestamps at base+30 and base+40 (>= base+25)

    @pytest.mark.asyncio
    async def test_query_limit(self, storage):
        """Limit caps the number of returned rows."""
        base = time.time()
        for i in range(10):
            await storage.store_timeseries(
                agent_id="bot-1",
                metric_name="sharpe_30d",
                value=float(i),
                timestamp=base + i,
                data_source="self_reported",
            )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d", limit=3)
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_query_returns_descending_timestamp(self, storage):
        """Results are ordered by timestamp descending (newest first)."""
        base = time.time()
        for i in range(3):
            await storage.store_timeseries(
                agent_id="bot-1",
                metric_name="sharpe_30d",
                value=float(i),
                timestamp=base + i,
                data_source="self_reported",
            )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d")
        assert rows[0]["timestamp"] > rows[-1]["timestamp"]

    @pytest.mark.asyncio
    async def test_query_empty(self, storage):
        """Query with no data returns empty list."""
        rows = await storage.query_timeseries("nonexistent", "sharpe_30d")
        assert rows == []


class TestGetLatestMetric:
    @pytest.mark.asyncio
    async def test_get_latest_returns_newest(self, storage):
        """get_latest_metric returns the most recent entry."""
        base = time.time()
        for i in range(3):
            await storage.store_timeseries(
                agent_id="bot-1",
                metric_name="sharpe_30d",
                value=float(i + 1),
                timestamp=base + i,
                data_source="self_reported",
            )
        row = await storage.get_latest_metric("bot-1", "sharpe_30d")
        assert row is not None
        assert row["value"] == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_get_latest_returns_none_when_empty(self, storage):
        """get_latest_metric returns None when no data exists."""
        row = await storage.get_latest_metric("nonexistent", "sharpe_30d")
        assert row is None


class TestUniqueConstraint:
    @pytest.mark.asyncio
    async def test_duplicate_replaces(self, storage):
        """INSERT OR REPLACE on unique(agent_id, metric_name, window_days, timestamp)."""
        ts = time.time()
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            value=1.0,
            timestamp=ts,
            data_source="self_reported",
        )
        await storage.store_timeseries(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            value=2.0,
            timestamp=ts,
            data_source="exchange_api",
        )
        rows = await storage.query_timeseries("bot-1", "sharpe_30d")
        assert len(rows) == 1
        assert rows[0]["value"] == pytest.approx(2.0)
        assert rows[0]["data_source"] == "exchange_api"


class TestAggregates:
    @pytest.mark.asyncio
    async def test_upsert_and_get_aggregate(self, storage):
        """Upsert aggregate then retrieve it."""
        await storage.upsert_aggregate(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            period="7d",
            avg_value=2.0,
            min_value=1.5,
            max_value=2.5,
            stddev=0.3,
            sample_count=10,
        )
        agg = await storage.get_aggregates("bot-1", "sharpe_30d", "7d")
        assert agg is not None
        assert agg["avg_value"] == pytest.approx(2.0)
        assert agg["min_value"] == pytest.approx(1.5)
        assert agg["max_value"] == pytest.approx(2.5)
        assert agg["stddev"] == pytest.approx(0.3)
        assert agg["sample_count"] == 10

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self, storage):
        """Second upsert replaces previous aggregate."""
        await storage.upsert_aggregate(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            period="7d",
            avg_value=1.0,
            min_value=0.5,
            max_value=1.5,
            stddev=0.2,
            sample_count=5,
        )
        await storage.upsert_aggregate(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            period="7d",
            avg_value=3.0,
            min_value=2.0,
            max_value=4.0,
            stddev=0.5,
            sample_count=20,
        )
        agg = await storage.get_aggregates("bot-1", "sharpe_30d", "7d")
        assert agg["avg_value"] == pytest.approx(3.0)
        assert agg["sample_count"] == 20

    @pytest.mark.asyncio
    async def test_get_aggregate_returns_none_when_missing(self, storage):
        """get_aggregates returns None for missing data."""
        agg = await storage.get_aggregates("nonexistent", "sharpe_30d", "7d")
        assert agg is None


class TestMetricLeaderboard:
    @pytest.mark.asyncio
    async def test_leaderboard_ordering(self, storage):
        """Leaderboard returns agents sorted by latest value descending."""
        now = time.time()
        for i, agent in enumerate(["bot-a", "bot-b", "bot-c"]):
            await storage.store_timeseries(
                agent_id=agent,
                metric_name="sharpe_30d",
                value=float(i + 1),  # 1.0, 2.0, 3.0
                timestamp=now,
                data_source="self_reported",
            )
        board = await storage.get_metric_leaderboard("sharpe_30d", limit=10)
        assert len(board) == 3
        assert board[0]["agent_id"] == "bot-c"
        assert board[0]["value"] == pytest.approx(3.0)
        assert board[-1]["agent_id"] == "bot-a"

    @pytest.mark.asyncio
    async def test_leaderboard_limit(self, storage):
        """Leaderboard respects limit."""
        now = time.time()
        for i in range(5):
            await storage.store_timeseries(
                agent_id=f"bot-{i}",
                metric_name="pnl_30d",
                value=float(i * 100),
                timestamp=now,
                data_source="self_reported",
            )
        board = await storage.get_metric_leaderboard("pnl_30d", limit=2)
        assert len(board) == 2

    @pytest.mark.asyncio
    async def test_leaderboard_empty(self, storage):
        """Leaderboard returns empty list when no data."""
        board = await storage.get_metric_leaderboard("nonexistent_metric", limit=10)
        assert board == []
