"""Tests for the metrics ingestion API tools (PRD 012).

Tests are written against the IdentityAPI and IdentityStorage directly,
since gateway tool functions are thin wrappers.
"""

from __future__ import annotations

import json
import time

import pytest

from products.identity.src.crypto import AgentCrypto


class TestIngestMetrics:
    @pytest.mark.asyncio
    async def test_ingest_single_metric(self, api, storage):
        """Ingesting a single metric stores it in timeseries."""
        await api.register_agent("ingest-bot")
        await api.ingest_timeseries(
            agent_id="ingest-bot",
            metrics={"sharpe_30d": 2.5},
        )
        rows = await storage.query_timeseries("ingest-bot", "sharpe_30d")
        assert len(rows) == 1
        assert rows[0]["value"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_ingest_batch_metrics(self, api, storage):
        """Ingesting multiple metrics stores all of them."""
        await api.register_agent("batch-bot")
        await api.ingest_timeseries(
            agent_id="batch-bot",
            metrics={"sharpe_30d": 2.0, "pnl_30d": 500.0, "win_rate_30d": 0.65},
        )
        for name in ["sharpe_30d", "pnl_30d", "win_rate_30d"]:
            rows = await storage.query_timeseries("batch-bot", name)
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_ingest_invalid_metric_rejected(self, api):
        """Invalid metric names are rejected."""
        await api.register_agent("bad-metric-bot")
        result = await api.ingest_timeseries(
            agent_id="bad-metric-bot",
            metrics={"invalid_metric": 1.0, "sharpe_30d": 2.0},
        )
        assert result["rejected"] == 1
        assert result["accepted"] == 1

    @pytest.mark.asyncio
    async def test_ingest_dedup_on_same_timestamp(self, api, storage):
        """Duplicate timestamp for same agent+metric replaces."""
        await api.register_agent("dedup-bot")
        ts = time.time()
        await api.ingest_timeseries(
            agent_id="dedup-bot",
            metrics={"sharpe_30d": 1.0},
            timestamp=ts,
        )
        await api.ingest_timeseries(
            agent_id="dedup-bot",
            metrics={"sharpe_30d": 2.0},
            timestamp=ts,
        )
        rows = await storage.query_timeseries("dedup-bot", "sharpe_30d")
        assert len(rows) == 1
        assert rows[0]["value"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_ingest_with_signature(self, api, storage):
        """Signed ingestion sets data_source to agent_signed."""
        reg = await api.register_agent("signed-ingest")
        priv = reg.private_key
        metrics = {"sharpe_30d": 3.0}
        nonce = "ingest-nonce-1"
        canonical = json.dumps(
            {"metrics": metrics, "nonce": nonce},
            sort_keys=True,
            separators=(",", ":"),
        )
        sig = AgentCrypto.sign(priv, canonical.encode())
        await api.ingest_timeseries(
            agent_id="signed-ingest",
            metrics=metrics,
            signature=sig,
            nonce=nonce,
        )
        rows = await storage.query_timeseries("signed-ingest", "sharpe_30d")
        assert rows[0]["data_source"] == "agent_signed"

    @pytest.mark.asyncio
    async def test_ingest_returns_accepted_count(self, api):
        """Ingest returns accepted and rejected counts."""
        await api.register_agent("count-bot")
        result = await api.ingest_timeseries(
            agent_id="count-bot",
            metrics={"sharpe_30d": 2.0, "pnl_30d": 100.0},
        )
        assert result["accepted"] == 2
        assert result["rejected"] == 0

    @pytest.mark.asyncio
    async def test_ingest_agent_not_found(self, api):
        """Ingest for unknown agent raises error."""
        from products.identity.src.api import AgentNotFoundError

        with pytest.raises(AgentNotFoundError):
            await api.ingest_timeseries(
                agent_id="ghost-bot",
                metrics={"sharpe_30d": 1.0},
            )


class TestQueryMetrics:
    @pytest.mark.asyncio
    async def test_query_range(self, api, storage):
        """query_agent_timeseries returns data within range."""
        await api.register_agent("query-bot")
        base = time.time() - 100
        for i in range(5):
            await storage.store_timeseries(
                agent_id="query-bot",
                metric_name="sharpe_30d",
                value=float(i),
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        rows = await api.query_agent_timeseries(
            agent_id="query-bot",
            metric_name="sharpe_30d",
            since=base + 25,
            limit=10,
        )
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_query_empty(self, api):
        """query for non-existent agent returns empty."""
        rows = await api.query_agent_timeseries(agent_id="no-data", metric_name="sharpe_30d")
        assert rows == []


class TestGetMetricDeltas:
    @pytest.mark.asyncio
    async def test_deltas_returns_current_and_previous(self, api, storage):
        """get_metric_deltas compares latest value to previous."""
        await api.register_agent("delta-bot")
        base = time.time() - 100
        await storage.store_timeseries(
            agent_id="delta-bot",
            metric_name="sharpe_30d",
            value=2.0,
            timestamp=base,
            data_source="self_reported",
        )
        await storage.store_timeseries(
            agent_id="delta-bot",
            metric_name="sharpe_30d",
            value=3.0,
            timestamp=base + 50,
            data_source="self_reported",
        )
        deltas = await api.get_metric_deltas("delta-bot")
        assert "sharpe_30d" in deltas
        assert deltas["sharpe_30d"]["current"] == pytest.approx(3.0)
        assert deltas["sharpe_30d"]["previous"] == pytest.approx(2.0)
        assert deltas["sharpe_30d"]["absolute_delta"] == pytest.approx(1.0)


class TestGetMetricAverages:
    @pytest.mark.asyncio
    async def test_averages_from_aggregates(self, api, storage):
        """get_metric_averages reads from metric_aggregates."""
        await api.register_agent("avg-bot")
        await storage.upsert_aggregate(
            agent_id="avg-bot",
            metric_name="sharpe_30d",
            period="30d",
            avg_value=2.5,
            min_value=1.0,
            max_value=4.0,
            stddev=0.8,
            sample_count=30,
        )
        avgs = await api.get_metric_averages("avg-bot", period="30d")
        assert "sharpe_30d" in avgs
        assert avgs["sharpe_30d"]["avg_value"] == pytest.approx(2.5)

    @pytest.mark.asyncio
    async def test_averages_empty_returns_empty(self, api):
        """get_metric_averages with no data returns empty dict."""
        avgs = await api.get_metric_averages("no-data-bot", period="7d")
        assert avgs == {}
