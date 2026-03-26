# PRD-005: Agent Trust & Reputation API

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

AI agents cannot programmatically answer "Can I trust this MCP server or agent?" There are 16,000+ MCP servers with no quality signal. 53% use static API keys, 30 CVEs were filed in 60 days, and developer sentiment is "95% are garbage." Agents making autonomous tool-selection decisions have no data to differentiate reliable from unreliable services.

## Target Buyer

- Agent developers building multi-tool workflows (need to pick reliable tools)
- MCP server operators wanting a verified quality badge
- Enterprise teams evaluating agent tool stacks

## Product Scope

A scoring engine + API that evaluates MCP servers and agent services on measurable dimensions.

### Trust Dimensions (scored 0-100 each)

1. **Reliability** — latency p50/p95/p99, uptime percentage, error rate, timeout rate
2. **Security** — TLS enabled, authentication required, input validation present, known CVEs, dependency freshness
3. **Documentation** — tool descriptions present, parameter descriptions present, examples provided, response format documented
4. **Responsiveness** — average response time, response consistency (stddev), cold-start penalty

### Composite Trust Score

Weighted average: `reliability * 0.35 + security * 0.30 + documentation * 0.20 + responsiveness * 0.15`

Result: single 0-100 score with dimensional breakdown.

### Components

- **Prober** — automated health checker that periodically pings registered MCP servers
  - Connects via stdio or HTTP transport
  - Calls `list_tools()` to check availability and documentation
  - Issues test calls to measure latency and error handling
  - Records all metrics to time-series storage

- **Security Scanner** — static assessment
  - Check transport encryption (TLS)
  - Check authentication requirements
  - Check for known CVE patterns in declared dependencies
  - Check input validation (send malformed inputs, verify rejection)

- **Score Engine** — computes and caches trust scores
  - Rolling window calculations (24h, 7d, 30d)
  - Decay function for stale data (score confidence drops without recent probes)
  - Historical trend tracking

- **API** — query interface for agents
  - `GET /v1/scores/{server_id}` — current trust score + dimensional breakdown
  - `GET /v1/scores/{server_id}/history` — score over time
  - `POST /v1/servers/register` — register a new server for probing
  - `GET /v1/servers/search` — search registered servers by category/score threshold

### Data Model

```
Server:
  id, name, url, transport_type, registered_at, last_probed_at

ProbeResult:
  server_id, timestamp, latency_ms, status_code, error, tools_count, tools_documented

SecurityScan:
  server_id, timestamp, tls_enabled, auth_required, input_validation_score, cve_count

TrustScore:
  server_id, timestamp, window (24h/7d/30d),
  reliability_score, security_score, documentation_score, responsiveness_score,
  composite_score, confidence (0-1 based on data freshness)
```

## Pricing Hypothesis

- Free tier: 100 score lookups/day, public scores only
- Pro: $29/month — unlimited lookups, historical data, webhook alerts on score changes
- Enterprise: $99/month — private server scanning, custom weights, SLA

## Success Metrics

- 50+ servers registered in 30 days
- 10+ external API consumers in 60 days
- Trust scores correlate with actual user satisfaction (validate with manual review)

## Kill Criteria

- <10 servers registered in 30 days → insufficient adoption, re-evaluate
- <3 API consumers in 60 days → no demand for programmatic trust data
- Scores do not differentiate good from bad servers (manual validation fails) → scoring model needs rework
