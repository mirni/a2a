"""Tests for observability logic (PRD 013).

Covers: delta computation, z-score, trend classification, aggregate refresh,
alert evaluation, edge cases with insufficient data.
"""

from __future__ import annotations

import math
import time

import pytest


class TestComputeDelta:
    @pytest.mark.asyncio
    async def test_delta_with_aggregate(self, storage):
        """compute_delta returns delta comparing latest to 30d aggregate."""
        from products.identity.src.observability import compute_delta

        now = time.time()
        await storage.store_timeseries(
            agent_id="obs-bot",
            metric_name="sharpe_30d",
            value=3.0,
            timestamp=now,
            data_source="self_reported",
        )
        await storage.upsert_aggregate(
            agent_id="obs-bot",
            metric_name="sharpe_30d",
            period="30d",
            avg_value=2.0,
            min_value=1.0,
            max_value=2.5,
            stddev=0.5,
            sample_count=30,
        )
        delta = await compute_delta(storage, "obs-bot", "sharpe_30d")
        assert delta is not None
        assert delta.current_value == pytest.approx(3.0)
        assert delta.baseline_value == pytest.approx(2.0)
        assert delta.absolute_delta == pytest.approx(1.0)
        assert delta.z_score == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_delta_no_data_returns_none(self, storage):
        """compute_delta returns None when no time-series data exists."""
        from products.identity.src.observability import compute_delta

        delta = await compute_delta(storage, "ghost-bot", "sharpe_30d")
        assert delta is None

    @pytest.mark.asyncio
    async def test_delta_no_aggregate_returns_none(self, storage):
        """compute_delta returns None when aggregate is missing."""
        from products.identity.src.observability import compute_delta

        now = time.time()
        await storage.store_timeseries(
            agent_id="obs-bot-2",
            metric_name="sharpe_30d",
            value=3.0,
            timestamp=now,
            data_source="self_reported",
        )
        delta = await compute_delta(storage, "obs-bot-2", "sharpe_30d")
        assert delta is None


class TestZScore:
    @pytest.mark.asyncio
    async def test_significant_z_score(self, storage):
        """|z_score| > 2.0 marks delta as significant."""
        from products.identity.src.observability import compute_delta

        now = time.time()
        await storage.store_timeseries(
            agent_id="sig-bot",
            metric_name="sharpe_30d",
            value=5.0,
            timestamp=now,
            data_source="self_reported",
        )
        await storage.upsert_aggregate(
            agent_id="sig-bot",
            metric_name="sharpe_30d",
            period="30d",
            avg_value=2.0,
            min_value=1.0,
            max_value=3.0,
            stddev=1.0,
            sample_count=30,
        )
        delta = await compute_delta(storage, "sig-bot", "sharpe_30d")
        assert delta.z_score == pytest.approx(3.0)
        assert delta.is_significant is True

    @pytest.mark.asyncio
    async def test_non_significant_z_score(self, storage):
        """|z_score| <= 2.0 is not significant."""
        from products.identity.src.observability import compute_delta

        now = time.time()
        await storage.store_timeseries(
            agent_id="stable-bot",
            metric_name="sharpe_30d",
            value=2.5,
            timestamp=now,
            data_source="self_reported",
        )
        await storage.upsert_aggregate(
            agent_id="stable-bot",
            metric_name="sharpe_30d",
            period="30d",
            avg_value=2.0,
            min_value=1.5,
            max_value=2.5,
            stddev=1.0,
            sample_count=30,
        )
        delta = await compute_delta(storage, "stable-bot", "sharpe_30d")
        assert delta.z_score == pytest.approx(0.5)
        assert delta.is_significant is False

    @pytest.mark.asyncio
    async def test_zero_stddev_z_score(self, storage):
        """Zero stddev yields z_score = 0.0 to avoid division by zero."""
        from products.identity.src.observability import compute_delta

        now = time.time()
        await storage.store_timeseries(
            agent_id="flat-bot",
            metric_name="sharpe_30d",
            value=2.5,
            timestamp=now,
            data_source="self_reported",
        )
        await storage.upsert_aggregate(
            agent_id="flat-bot",
            metric_name="sharpe_30d",
            period="30d",
            avg_value=2.0,
            min_value=2.0,
            max_value=2.0,
            stddev=0.0,
            sample_count=10,
        )
        delta = await compute_delta(storage, "flat-bot", "sharpe_30d")
        assert delta.z_score == pytest.approx(0.0)


class TestTrendDetection:
    @pytest.mark.asyncio
    async def test_improving_trend(self, storage):
        """Monotonically increasing values yield 'improving'."""
        from products.identity.src.observability import detect_trend

        base = time.time() - 100
        for i in range(5):
            await storage.store_timeseries(
                agent_id="trend-bot",
                metric_name="sharpe_30d",
                value=float(i + 1),
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        trend = await detect_trend(storage, "trend-bot", "sharpe_30d", lookback=5)
        assert trend == "improving"

    @pytest.mark.asyncio
    async def test_declining_trend(self, storage):
        """Monotonically decreasing values yield 'declining'."""
        from products.identity.src.observability import detect_trend

        base = time.time() - 100
        for i in range(5):
            await storage.store_timeseries(
                agent_id="decline-bot",
                metric_name="sharpe_30d",
                value=float(5 - i),
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        trend = await detect_trend(storage, "decline-bot", "sharpe_30d", lookback=5)
        assert trend == "declining"

    @pytest.mark.asyncio
    async def test_stable_trend(self, storage):
        """Same value repeated yields 'stable'."""
        from products.identity.src.observability import detect_trend

        base = time.time() - 100
        for i in range(5):
            await storage.store_timeseries(
                agent_id="stable-trend-bot",
                metric_name="sharpe_30d",
                value=2.0,
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        trend = await detect_trend(storage, "stable-trend-bot", "sharpe_30d", lookback=5)
        assert trend == "stable"

    @pytest.mark.asyncio
    async def test_volatile_trend(self, storage):
        """Alternating up/down yields 'volatile'."""
        from products.identity.src.observability import detect_trend

        base = time.time() - 100
        values = [1.0, 5.0, 1.0, 5.0, 1.0]
        for i, val in enumerate(values):
            await storage.store_timeseries(
                agent_id="volatile-bot",
                metric_name="sharpe_30d",
                value=val,
                timestamp=base + i * 10,
                data_source="self_reported",
            )
        trend = await detect_trend(storage, "volatile-bot", "sharpe_30d", lookback=5)
        assert trend == "volatile"

    @pytest.mark.asyncio
    async def test_insufficient_data(self, storage):
        """Less than 2 data points returns 'stable' (no trend detectable)."""
        from products.identity.src.observability import detect_trend

        await storage.store_timeseries(
            agent_id="one-point-bot",
            metric_name="sharpe_30d",
            value=2.0,
            timestamp=time.time(),
            data_source="self_reported",
        )
        trend = await detect_trend(storage, "one-point-bot", "sharpe_30d", lookback=5)
        assert trend == "stable"


class TestComputeMovingAverages:
    @pytest.mark.asyncio
    async def test_compute_stores_aggregate(self, storage):
        """compute_moving_averages stores 7d/30d/90d aggregates."""
        from products.identity.src.observability import compute_moving_averages

        now = time.time()
        for i in range(10):
            await storage.store_timeseries(
                agent_id="mavg-bot",
                metric_name="sharpe_30d",
                value=float(i + 1),
                timestamp=now - (9 - i) * 86400,
                data_source="self_reported",
            )
        await compute_moving_averages(storage, "mavg-bot", "sharpe_30d")

        agg_7d = await storage.get_aggregates("mavg-bot", "sharpe_30d", "7d")
        agg_30d = await storage.get_aggregates("mavg-bot", "sharpe_30d", "30d")
        agg_90d = await storage.get_aggregates("mavg-bot", "sharpe_30d", "90d")
        assert agg_7d is not None
        assert agg_30d is not None
        assert agg_90d is not None
        assert agg_30d["sample_count"] == 10


class TestAlertEvaluation:
    def test_evaluate_alerts_triggers_on_threshold(self):
        """Alert triggers when z-score exceeds rule threshold."""
        from products.identity.src.observability import MetricDelta, evaluate_alerts

        delta = MetricDelta(
            metric_name="sharpe_30d",
            current_value=5.0,
            baseline_value=2.0,
            absolute_delta=3.0,
            relative_delta=150.0,
            z_score=3.0,
            is_significant=True,
            trend="improving",
        )
        rules = [{"metric_name": "sharpe_30d", "z_score_threshold": 2.0, "action": "notify"}]
        alerts = evaluate_alerts(delta, rules)
        assert len(alerts) == 1
        assert alerts[0]["action"] == "notify"

    def test_evaluate_alerts_no_trigger(self):
        """No alert when z-score below threshold."""
        from products.identity.src.observability import MetricDelta, evaluate_alerts

        delta = MetricDelta(
            metric_name="sharpe_30d",
            current_value=2.2,
            baseline_value=2.0,
            absolute_delta=0.2,
            relative_delta=10.0,
            z_score=0.4,
            is_significant=False,
            trend="stable",
        )
        rules = [{"metric_name": "sharpe_30d", "z_score_threshold": 2.0, "action": "notify"}]
        alerts = evaluate_alerts(delta, rules)
        assert len(alerts) == 0
