"""Observability logic for agent performance metrics (PRD 013).

Computes deltas, moving averages, trend detection, and alert evaluation
against time-series data stored in IdentityStorage.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from .storage import IdentityStorage


@dataclass
class MetricDelta:
    """Result of comparing a metric's latest value to its rolling baseline."""

    metric_name: str
    current_value: float
    baseline_value: float  # 30d moving average
    absolute_delta: float
    relative_delta: float
    z_score: float
    is_significant: bool  # |z_score| > 2.0
    trend: str  # "improving" | "declining" | "stable" | "volatile"


async def compute_delta(
    storage: IdentityStorage,
    agent_id: str,
    metric_name: str,
) -> MetricDelta | None:
    """Compare latest value to 30d aggregate.

    Returns None if no time-series data or no aggregate exists.
    """
    latest = await storage.get_latest_metric(agent_id, metric_name)
    if latest is None:
        return None

    agg = await storage.get_aggregates(agent_id, metric_name, "30d")
    if agg is None:
        return None

    current = latest["value"]
    baseline = agg["avg_value"]
    stddev = agg["stddev"]
    absolute_delta = current - baseline

    if stddev and stddev > 0:
        z_score = absolute_delta / stddev
    else:
        z_score = 0.0

    relative_delta = (absolute_delta / baseline * 100) if baseline != 0 else 0.0
    is_significant = abs(z_score) > 2.0

    trend = await detect_trend(storage, agent_id, metric_name, lookback=5)

    return MetricDelta(
        metric_name=metric_name,
        current_value=current,
        baseline_value=baseline,
        absolute_delta=absolute_delta,
        relative_delta=relative_delta,
        z_score=z_score,
        is_significant=is_significant,
        trend=trend,
    )


async def detect_trend(
    storage: IdentityStorage,
    agent_id: str,
    metric_name: str,
    lookback: int = 5,
) -> str:
    """Classify the recent direction of a metric.

    Returns one of: "improving", "declining", "stable", "volatile".

    Uses the last *lookback* data points (ordered oldest → newest).
    """
    rows = await storage.query_timeseries(agent_id, metric_name, limit=lookback)
    if len(rows) < 2:
        return "stable"

    # Rows come newest-first; reverse to oldest-first for analysis
    values = [r["value"] for r in reversed(rows)]

    # Compute consecutive deltas
    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    positive = sum(1 for d in deltas if d > 0)
    negative = sum(1 for d in deltas if d < 0)
    zero = sum(1 for d in deltas if d == 0)
    total = len(deltas)

    if zero == total:
        return "stable"

    # Check for sign changes (volatility indicator)
    sign_changes = sum(
        1
        for i in range(len(deltas) - 1)
        if (deltas[i] > 0 and deltas[i + 1] < 0) or (deltas[i] < 0 and deltas[i + 1] > 0)
    )

    if sign_changes >= total * 0.5:
        return "volatile"

    if positive > negative:
        return "improving"
    if negative > positive:
        return "declining"

    return "stable"


async def compute_moving_averages(
    storage: IdentityStorage,
    agent_id: str,
    metric_name: str,
) -> None:
    """Compute and upsert 7d, 30d, 90d rolling aggregates from raw time-series."""
    now = time.time()
    periods = {"7d": 7, "30d": 30, "90d": 90}

    for period_name, days in periods.items():
        since = now - days * 86400
        rows = await storage.query_timeseries(agent_id, metric_name, since=since, limit=10000)
        if not rows:
            continue

        values = [r["value"] for r in rows]
        n = len(values)
        avg = sum(values) / n
        min_val = min(values)
        max_val = max(values)

        if n > 1:
            variance = sum((v - avg) ** 2 for v in values) / (n - 1)
            stddev = math.sqrt(variance)
        else:
            stddev = 0.0

        await storage.upsert_aggregate(
            agent_id=agent_id,
            metric_name=metric_name,
            period=period_name,
            avg_value=avg,
            min_value=min_val,
            max_value=max_val,
            stddev=stddev,
            sample_count=n,
        )


def evaluate_alerts(
    delta: MetricDelta,
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate a metric delta against alert rules.

    Each rule is a dict with:
        metric_name: str
        z_score_threshold: float
        action: str  (e.g. "notify", "escalate")

    Returns list of triggered alert dicts.
    """
    triggered: list[dict[str, Any]] = []
    for rule in rules:
        if rule["metric_name"] != delta.metric_name:
            continue
        threshold = rule.get("z_score_threshold", 2.0)
        if abs(delta.z_score) >= threshold:
            triggered.append({
                "metric_name": delta.metric_name,
                "z_score": delta.z_score,
                "threshold": threshold,
                "action": rule["action"],
                "current_value": delta.current_value,
                "baseline_value": delta.baseline_value,
            })
    return triggered
