# PRD 013: Observability Logic — Performance Deltas and Alerts

**Status:** Draft
**Author:** Platform Team
**Date:** 2026-03-29

## Problem

Consumers need to know when an agent's performance changes significantly. Currently the platform stores snapshots but doesn't detect or alert on performance degradation, trend shifts, or anomalies.

## Requirements

1. Detect significant performance changes (deltas) relative to rolling baselines
2. Compute and expose moving averages (7d, 30d, 90d) for each metric
3. Alert when metrics breach configurable thresholds
4. Support both absolute and relative (percentage) thresholds
5. Expose delta data via API for consumer decision-making

## Design

### 1. Delta Computation

For each metric submission, compute the delta against the rolling baseline:

```python
@dataclass
class MetricDelta:
    agent_id: str
    metric_name: str
    current_value: float
    baseline_value: float        # 30-day moving average
    absolute_delta: float        # current - baseline
    relative_delta: float        # (current - baseline) / baseline
    z_score: float              # (current - mean) / stddev
    is_significant: bool         # |z_score| > threshold
    timestamp: float
```

**Significance threshold:** |z-score| > 2.0 (configurable per metric)

### 2. Moving Averages

Computed on each ingestion or via periodic background job:

```python
async def compute_moving_averages(agent_id: str, metric_name: str):
    for period in ["7d", "30d", "90d"]:
        days = int(period.rstrip("d"))
        cutoff = time.time() - days * 86400
        rows = await storage.query_timeseries(
            agent_id, metric_name, since=cutoff
        )
        values = [r.value for r in rows]
        if values:
            avg = statistics.mean(values)
            stddev = statistics.stdev(values) if len(values) > 1 else 0.0
            await storage.upsert_aggregate(
                agent_id, metric_name, period,
                avg_value=avg,
                min_value=min(values),
                max_value=max(values),
                stddev=stddev,
                sample_count=len(values),
            )
```

### 3. Alert Rules

```python
@dataclass
class AlertRule:
    metric_name: str
    condition: str           # "below_baseline", "above_baseline", "z_score"
    threshold: float         # e.g., 2.0 for z-score, 0.2 for 20% drop
    severity: str           # "info", "warning", "critical"
    notify: list[str]       # ["webhook", "event_bus"]
```

**Built-in rules:**

| Metric | Condition | Threshold | Severity |
|--------|-----------|-----------|----------|
| sharpe_30d | below_baseline | -20% relative | warning |
| sharpe_30d | below_baseline | -50% relative | critical |
| max_drawdown_30d | above_baseline | +50% relative | critical |
| win_rate_30d | below_baseline | -15% relative | warning |
| p99_latency_ms | above_baseline | +100% relative | warning |

### 4. API Endpoints

#### Get metric deltas

```
GET /tools/get_metric_deltas
{
    "agent_id": "agent-7f3a2b",
    "metric_name": "sharpe_30d"  // optional, all metrics if omitted
}

Response:
{
    "deltas": [
        {
            "metric_name": "sharpe_30d",
            "current_value": 1.82,
            "baseline_30d": 2.10,
            "absolute_delta": -0.28,
            "relative_delta": -0.133,
            "z_score": -1.4,
            "is_significant": false,
            "trend": "declining"
        }
    ]
}
```

#### Get moving averages

```
GET /tools/get_metric_averages
{
    "agent_id": "agent-7f3a2b",
    "period": "30d"
}

Response:
{
    "averages": [
        {
            "metric_name": "sharpe_30d",
            "avg_value": 2.10,
            "min_value": 1.50,
            "max_value": 2.85,
            "stddev": 0.35,
            "sample_count": 720,
            "period": "30d"
        }
    ]
}
```

### 5. Event Integration

When a significant delta is detected, emit events:

```python
await event_bus.publish({
    "type": "metric.significant_change",
    "agent_id": agent_id,
    "metric_name": metric_name,
    "delta": {
        "current": current_value,
        "baseline": baseline_value,
        "z_score": z_score,
    },
    "severity": "warning",
    "timestamp": time.time(),
})
```

Consumers can subscribe via webhooks or the event bus to react to performance changes.

### 6. Trend Detection

Simple trend classification based on recent deltas:

| Pattern | Classification |
|---------|---------------|
| 3+ consecutive positive deltas | `improving` |
| 3+ consecutive negative deltas | `declining` |
| Alternating positive/negative | `volatile` |
| All deltas within 1 stddev | `stable` |

## Performance Considerations

- Delta computation: O(1) per submission (compare against cached aggregate)
- Aggregate recomputation: O(n) where n = samples in window, run async
- Alert evaluation: O(rules) per submission, typically <10 rules
- Total overhead per ingestion: <10ms

## Dependencies

- PRD 010: Time-series schema (storage layer)
- PRD 012: Ingestion API (data source)
- Existing event bus for alert delivery
- Existing webhook system for external notifications
