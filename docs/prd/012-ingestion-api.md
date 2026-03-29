# PRD 012: Metric Ingestion API

**Status:** Draft
**Author:** Platform Team
**Date:** 2026-03-29

## Problem

Agents (trading bots, signal providers, etc.) need to submit periodic metric heartbeats to the platform. Currently `submit_metrics` is a one-shot operation tied to the attestation flow. There's no lightweight, high-frequency ingestion endpoint for streaming metrics.

## Requirements

1. Accept metric heartbeats at up to 1-minute intervals per agent
2. Batch multiple metrics per submission
3. Support both authenticated (Ed25519 signed) and unauthenticated modes
4. Rate-limit to prevent abuse (configurable per tier)
5. Feed into time-series storage (PRD 010) and commitment system

## API Design

### Endpoint: `POST /metrics/ingest`

```json
{
    "agent_id": "agent-7f3a2b",
    "metrics": {
        "sharpe_30d": 2.35,
        "max_drawdown_30d": 3.1,
        "win_rate_30d": 0.61,
        "pnl_30d": 1250.00,
        "total_trades_30d": 47
    },
    "timestamp": 1711612800.0,
    "signature": "optional-ed25519-hex",
    "nonce": "optional-replay-nonce"
}
```

### Response: `200 OK`

```json
{
    "accepted": 5,
    "rejected": 0,
    "next_allowed_at": 1711612860.0
}
```

### Endpoint: `POST /metrics/ingest/batch`

For agents submitting on behalf of multiple sub-identities:

```json
{
    "submissions": [
        {
            "agent_id": "sub-agent7f3a2b-analyzer",
            "metrics": {"signal_accuracy_30d": 0.72}
        },
        {
            "agent_id": "sub-agent7f3a2b-executor",
            "metrics": {"p99_latency_ms": 45}
        }
    ],
    "parent_signature": "ed25519-hex-from-parent"
}
```

## Rate Limiting

| Tier | Max Frequency | Max Metrics/Submission | Daily Limit |
|------|--------------|----------------------|-------------|
| Free | 1/hour | 8 | 24 |
| Pro | 1/minute | 16 | 1,440 |
| Enterprise | 1/second | 32 | 86,400 |

Rate limits enforced via token bucket algorithm per agent_id.

## Processing Pipeline

```
Ingest Request
    ├── Validate agent_id exists
    ├── Verify signature (if provided)
    ├── Check rate limit
    ├── Validate metric names against SUPPORTED_METRICS
    │
    ├── Write to metric_timeseries (PRD 010)
    ├── Optionally create commitments (if attestation_mode=true)
    │
    ├── Emit event: "metrics.ingested"
    └── Return acceptance response
```

## Gateway Integration

New tool: `ingest_metrics`

```python
async def _ingest_metrics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Lightweight metric ingestion (no attestation by default)."""
    agent_id = params["agent_id"]
    metrics = params["metrics"]

    # Write to time-series storage
    for metric_name, value in metrics.items():
        await ctx.identity_api.storage.store_timeseries(
            agent_id=agent_id,
            metric_name=metric_name,
            value=value,
            timestamp=time.time(),
            data_source=params.get("data_source", "self_reported"),
        )

    return {"accepted": len(metrics), "rejected": 0}
```

## Deduplication

If the same (agent_id, metric_name, window_days, timestamp) arrives twice:
- `ON CONFLICT ... DO UPDATE SET value = excluded.value`
- Last-write-wins semantics
- Emit `metrics.updated` event instead of `metrics.ingested`

## Monitoring

- Metric: `ingestion_rate_per_agent` — alert if any agent exceeds 2x their tier limit
- Metric: `ingestion_latency_p99` — alert if > 100ms
- Metric: `ingestion_rejection_rate` — alert if > 5% of submissions rejected

## Open Questions

1. Should heartbeats automatically trigger re-attestation if values change significantly?
2. Should we support WebSocket streaming for sub-second metrics (latency monitoring)?
3. How to handle clock skew between agent and platform timestamps?
