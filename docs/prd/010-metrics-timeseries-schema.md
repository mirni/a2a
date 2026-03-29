# PRD 010: Time-Series Schema for Agent Metrics

**Status:** Draft
**Author:** Platform Team
**Date:** 2026-03-29

## Problem

Agent performance metrics (Sharpe, Sortino, max drawdown, win rate, PnL, etc.) are currently stored as point-in-time commitments in the identity system. There is no time-series storage for tracking metric evolution, computing rolling aggregates, or detecting performance degradation.

## Requirements

1. Store metric values with timestamps for any registered agent
2. Support diverse metric types: ratios (Sharpe, Sortino), percentages (drawdown, win rate), counts (trades), and currency (PnL, AUM)
3. Enable efficient queries: latest value, time range, rolling aggregates (30d, 90d)
4. Support at least 10,000 agents with hourly metric updates (240K rows/day)
5. Integrate with existing commitment/attestation system

## Proposed Schema

### Core table: `metric_timeseries`

```sql
CREATE TABLE metric_timeseries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    window_days INTEGER NOT NULL DEFAULT 30,
    timestamp REAL NOT NULL,              -- Unix epoch
    data_source TEXT NOT NULL DEFAULT 'self_reported',
    commitment_hash TEXT,                 -- FK to metric_commitments (optional)
    UNIQUE(agent_id, metric_name, window_days, timestamp)
);

-- Query patterns: latest per agent, range scans, rolling aggregates
CREATE INDEX idx_ts_agent_metric_time
    ON metric_timeseries(agent_id, metric_name, timestamp DESC);

-- Leaderboard queries: top agents by latest metric value
CREATE INDEX idx_ts_metric_time
    ON metric_timeseries(metric_name, timestamp DESC, value DESC);
```

### Aggregation table: `metric_aggregates`

Pre-computed rolling aggregates for dashboard queries:

```sql
CREATE TABLE metric_aggregates (
    agent_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    period TEXT NOT NULL,          -- '7d', '30d', '90d'
    avg_value REAL,
    min_value REAL,
    max_value REAL,
    stddev REAL,
    sample_count INTEGER,
    computed_at REAL NOT NULL,
    PRIMARY KEY(agent_id, metric_name, period)
);
```

## Query Patterns

| Query | SQL Pattern | Expected Latency |
|-------|-------------|-----------------|
| Latest metric for agent | `WHERE agent_id=? AND metric_name=? ORDER BY timestamp DESC LIMIT 1` | <5ms |
| 30-day history | `WHERE agent_id=? AND metric_name=? AND timestamp > ?` | <20ms |
| Leaderboard (top 50) | `WHERE metric_name=? ORDER BY timestamp DESC, value DESC LIMIT 50` | <50ms |
| Rolling 30d average | Read from `metric_aggregates` | <5ms |

## Data Volume Estimates

- 10,000 agents x 8 metrics x 24 updates/day = 1.92M rows/day
- At ~100 bytes/row = 192 MB/day raw
- With SQLite WAL + compression: ~50 MB/day
- 60-day retention before compression = 3 GB active data

## Retention Policy

See PRD 014 (Data Lifecycle) for full retention/compression strategy.

- **Hot tier** (0-60 days): Full resolution, all rows retained
- **Warm tier** (60-365 days): Hourly samples compressed to daily aggregates
- **Cold tier** (365+ days): Monthly summaries only

## Integration Points

1. **Ingestion API** (PRD 012): Receives metric heartbeats, writes to `metric_timeseries`
2. **Commitment system**: Each ingested value optionally creates a hiding commitment
3. **Observability** (PRD 013): Reads time-series for delta detection and alerts
4. **Leaderboard**: Reads aggregates for ranking

## Migration

New tables added via standard migration system (`products/shared/src/migrate.py`). No changes to existing `metric_commitments` or `attestations` tables.

## Open Questions

1. Should we support custom metric names beyond `SUPPORTED_METRICS`, or keep the fixed set?
2. Is SQLite sufficient at 10K agent scale, or should we plan for TimescaleDB/ClickHouse?
3. Should aggregates be computed on-write (simpler) or via background job (more flexible)?
