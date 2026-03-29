# PRD 014: Data Lifecycle — Retention and Compression Policy

**Status:** Draft
**Author:** Platform Team
**Date:** 2026-03-29

## Problem

The platform stores an ever-growing volume of time-series metrics, attestations, transaction records, and audit logs. With a 60 GB disk constraint, we need a clear retention and compression strategy that preserves data integrity while staying within capacity.

## Storage Budget (60 GB total)

| Category | Allocation | Rationale |
|----------|-----------|-----------|
| SQLite WAL + active DB | 20 GB | Primary operational data |
| Time-series metrics | 15 GB | Hot + warm tiers |
| Backups | 10 GB | 3 most recent backups |
| Attestations & commitments | 5 GB | Cryptographic proofs (never deleted) |
| Transaction ledger | 5 GB | Financial records (regulatory) |
| Audit logs | 3 GB | Security events |
| Headroom | 2 GB | Safety margin |

## Retention Tiers

### Tier 1: Hot Data (0–60 days)

Full resolution. All rows retained. No compression.

- Time-series: every ingested data point
- Transactions: every settlement, payment intent, escrow
- Attestations: all active (non-expired) attestations
- Audit logs: all events

**Estimated size:** ~3 GB/month at 10K agents

### Tier 2: Warm Data (60–365 days)

Aggregated. Individual data points compressed to daily summaries.

**Compression job (daily, 02:00 UTC):**

```sql
-- Step 1: Compute daily aggregates for records older than 60 days
INSERT OR REPLACE INTO metric_aggregates_daily
SELECT
    agent_id,
    metric_name,
    date(timestamp, 'unixepoch') as day,
    AVG(value) as avg_value,
    MIN(value) as min_value,
    MAX(value) as max_value,
    COUNT(*) as sample_count
FROM metric_timeseries
WHERE timestamp < unixepoch('now', '-60 days')
GROUP BY agent_id, metric_name, day;

-- Step 2: Delete raw data points (aggregates preserved)
DELETE FROM metric_timeseries
WHERE timestamp < unixepoch('now', '-60 days');
```

**Space savings:** ~90% reduction (hourly → daily aggregates)

### Tier 3: Cold Data (365+ days)

Monthly summaries only.

```sql
-- Compress daily aggregates older than 1 year to monthly
INSERT OR REPLACE INTO metric_aggregates_monthly
SELECT
    agent_id,
    metric_name,
    strftime('%Y-%m', day) as month,
    AVG(avg_value),
    MIN(min_value),
    MAX(max_value),
    SUM(sample_count)
FROM metric_aggregates_daily
WHERE day < date('now', '-365 days')
GROUP BY agent_id, metric_name, month;

DELETE FROM metric_aggregates_daily
WHERE day < date('now', '-365 days');
```

### Tier 4: Archive (permanent, immutable)

Never deleted:
- **Attestation signatures** — cryptographic proofs of metric claims
- **Commitment hashes** — SHA3-256 hiding commitments
- **Claim chains** — Merkle roots and leaf hashes
- **Financial settlements** — regulatory requirement

These are compact (mostly hex strings) and grow slowly (~50 MB/year at 10K agents).

## Compression Schedule

| Job | Frequency | Time | Retention |
|-----|-----------|------|-----------|
| Hot → Warm compression | Daily | 02:00 UTC | Keep 60 days hot |
| Warm → Cold compression | Weekly | Sunday 03:00 UTC | Keep 365 days warm |
| Audit log rotation | Weekly | Sunday 04:00 UTC | Keep 90 days |
| Backup rotation | Daily | 05:00 UTC | Keep 3 most recent |
| VACUUM | Weekly | Sunday 05:00 UTC | Reclaim SQLite space |

## Implementation

### Compression Worker

```python
class DataLifecycleManager:
    """Manages data retention, compression, and cleanup."""

    async def compress_hot_to_warm(self):
        """Aggregate and delete time-series data older than 60 days."""
        cutoff = time.time() - 60 * 86400
        # ... aggregate + delete as shown above

    async def compress_warm_to_cold(self):
        """Aggregate daily to monthly for data older than 365 days."""
        # ...

    async def rotate_audit_logs(self):
        """Delete audit log entries older than 90 days."""
        cutoff = time.time() - 90 * 86400
        await self.db.execute(
            "DELETE FROM audit_log WHERE timestamp < ?", (cutoff,)
        )

    async def rotate_backups(self, keep: int = 3):
        """Keep only the N most recent backups."""
        # List backups, delete oldest beyond keep count

    async def vacuum(self):
        """Reclaim disk space after deletions."""
        await self.db.execute("VACUUM")
```

### Disk Usage Monitoring

```python
async def check_disk_usage():
    """Alert if disk usage exceeds thresholds."""
    usage = shutil.disk_usage("/data")
    pct = usage.used / usage.total * 100

    if pct > 90:
        # CRITICAL: emergency compression
        await lifecycle.compress_hot_to_warm()
        await lifecycle.vacuum()
    elif pct > 80:
        # WARNING: emit alert
        await event_bus.publish({
            "type": "system.disk_warning",
            "usage_pct": pct,
        })
```

## Capacity Planning

| Scale | Agents | Metrics/day | Raw/day | After compression |
|-------|--------|-------------|---------|------------------|
| MVP | 100 | 19.2K | 1.9 MB | 0.2 MB |
| Growth | 1,000 | 192K | 19 MB | 2 MB |
| Scale | 10,000 | 1.92M | 192 MB | 20 MB |
| Limit | 50,000 | 9.6M | 960 MB | 100 MB |

At 10K agents with 60-day hot retention: ~12 GB active data (within 15 GB budget).

## Migration

New tables:
- `metric_aggregates_daily` — daily aggregates for warm tier
- `metric_aggregates_monthly` — monthly aggregates for cold tier

New scheduler jobs:
- `compress_hot_to_warm` — daily at 02:00 UTC
- `compress_warm_to_cold` — weekly Sunday 03:00 UTC
- `rotate_audit_logs` — weekly Sunday 04:00 UTC
- `vacuum_db` — weekly Sunday 05:00 UTC

## Monitoring

- `disk_usage_pct` — current disk usage percentage
- `hot_tier_size_mb` — size of active time-series data
- `compression_duration_ms` — time taken for compression jobs
- `rows_compressed` — number of rows aggregated per compression run
- `rows_deleted` — number of raw rows deleted per run
