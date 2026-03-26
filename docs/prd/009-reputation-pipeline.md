# PRD-009: Reputation Data Collection Pipeline

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

The trust scoring engine can compute scores from probe results and security scans, but nothing is generating that data continuously. Without automated monitoring, trust scores become stale and unreliable. Agents need fresh, continuous reliability data to make autonomous decisions.

## Target Buyer

- Same as trust API users
- Marketplace operators need fresh data for service rankings
- Agents making payment decisions need current reliability info

## Product Scope

### Probe Scheduler

Continuously monitors registered MCP servers:

```python
from a2a_reputation import ReputationPipeline

pipeline = ReputationPipeline(
    trust_storage=trust_storage,
    probe_interval_seconds=300,  # 5 min default
    scan_interval_seconds=3600,  # 1 hr security scans
)

# Register servers to monitor
await pipeline.add_target("https://mcp-stripe.example.com", server_id="svc-stripe")

# Start continuous monitoring
await pipeline.start()

# Graceful shutdown
await pipeline.stop()
```

### Health Probes

Each probe cycle collects:
- **Latency** — round-trip time to server health endpoint
- **Availability** — successful response (2xx) vs failure
- **Error classification** — timeout, connection refused, 4xx, 5xx
- **Response validation** — correct content-type, valid MCP response format

### Security Scans

Periodic deeper checks:
- **TLS configuration** — certificate validity, protocol version
- **Header security** — CORS, CSP, HSTS presence
- **Authentication check** — verifies auth is required (not open)
- **Version detection** — MCP protocol version, server version

### Score Aggregation

After each probe batch, recompute trust scores:

```python
# Automatic: after probes complete, scores update
# Manual trigger also available:
await pipeline.recompute_scores(server_id="svc-stripe")
```

### Components

- **ReputationPipeline** — orchestrates the full collection loop
  - `add_target()` / `remove_target()` — manage monitored servers
  - `start()` / `stop()` — run/stop the background loop
  - `run_once()` — single probe cycle (for testing)
  - `recompute_scores()` — trigger score recalculation

- **ProbeWorker** — executes individual health probes
  - HTTP health check with configurable timeout
  - Stores results in trust storage
  - Classifies errors by type

- **ScanWorker** — executes security scans
  - TLS certificate checking
  - Header analysis
  - Authentication verification
  - Stores results in trust storage

- **Aggregator** — recomputes scores from raw data
  - Calls trust scoring engine's `compute_trust_score()`
  - Handles windowed data (last 24h by default)
  - Updates stored scores

### Storage

Uses existing trust storage tables:
- `servers` — registered servers (already exists)
- `probe_results` — individual probe records (already exists)
- `security_scans` — scan results (already exists)
- `trust_scores` — computed scores (already exists)

New table:
- `probe_targets` — servers to monitor with probe/scan intervals

## Success Metrics

- 1000+ probe results collected per day
- Score freshness: <10 min average age
- Probe p99 latency <5s
- Zero missed probe cycles in 24h

## Kill Criteria

- Probe infrastructure consumes >$50/mo compute → optimize before scaling
- Scores not correlating with actual outages → scoring algorithm needs revision
