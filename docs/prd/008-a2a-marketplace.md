# PRD-008: Agent-to-Agent Service Marketplace

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

Agents have no way to discover services offered by other agents. Current MCP server directories are human-facing, unstructured, and lack pricing/SLA information. An agent cannot programmatically answer: "Which service can do X, at what cost, with what reliability?"

## Target Buyer

- MCP server operators who want to list and monetize their tools
- Agent developers who need their agents to dynamically discover services
- Trading/analytics agents that need data feeds, execution services, etc.

## Product Scope

### Service Registration

Providers register machine-readable service descriptions:

```python
from a2a_marketplace import Marketplace

marketplace = Marketplace(storage=storage)

await marketplace.register_service(
    provider_id="data-agent-1",
    name="Real-Time Market Data",
    description="Live price feeds for 500+ crypto pairs",
    category="market-data",
    tools=["get_price", "get_orderbook", "get_trades"],
    pricing={"model": "per_call", "cost": 0.5, "currency": "credits"},
    sla={"uptime": 99.9, "max_latency_ms": 200},
    tags=["crypto", "real-time", "market-data"],
)
```

### Service Discovery

Agents search for services programmatically:

```python
# Search by category
results = await marketplace.search(
    category="market-data",
    min_trust_score=70,
    max_cost=1.0,
    sort_by="trust_score",
)

# Search by capability
results = await marketplace.search(
    query="crypto price feed",
    min_trust_score=50,
)

# Get specific service details
service = await marketplace.get_service(service_id="svc-123")
```

### Auto-Selection

Agent can request best-match provider:

```python
match = await marketplace.best_match(
    query="crypto orderbook data",
    budget=1.0,
    min_trust_score=60,
    prefer="cost",  # or "trust" or "latency"
)
# Returns top provider with connection details
```

### Components

- **Marketplace** — main API for registration, discovery, and matching
  - `register_service()` / `update_service()` / `deactivate_service()`
  - `search()` — full-text + structured filtering
  - `best_match()` — ranked selection with preferences
  - `get_service()` — single service details with trust score
  - `list_categories()` — browse available categories

- **Marketplace Storage** — SQLite tables:
  - `services` — service listings with structured metadata
  - `service_tools` — tools offered by each service
  - `service_tags` — searchable tags
  - `service_reviews` — agent-submitted reviews (future)

- **Trust Integration** — every search result includes live trust score
  - Services below configurable trust threshold are flagged
  - Trust score included in ranking algorithm for `best_match()`

- **Payment Integration** — initiate payment when selecting a service
  - `marketplace.purchase()` — creates payment intent + returns connection info

## Service Listing Schema

```json
{
  "id": "svc-abc123",
  "provider_id": "data-agent-1",
  "name": "Real-Time Market Data",
  "description": "Live price feeds for 500+ crypto pairs",
  "category": "market-data",
  "tools": ["get_price", "get_orderbook"],
  "pricing": {"model": "per_call", "cost": 0.5},
  "sla": {"uptime": 99.9, "max_latency_ms": 200},
  "trust_score": 87,
  "tags": ["crypto", "real-time"],
  "status": "active",
  "created_at": "2026-03-26T12:00:00Z"
}
```

## Success Metrics

- 20+ services registered in first 30 days
- 100+ search queries in first 30 days
- 5+ completed purchases through marketplace in 60 days
- Search p95 latency <50ms

## Kill Criteria

- <5 service registrations in 30 days → no supply
- <20 search queries in 30 days → no demand
- Zero purchases in 60 days → marketplace not driving transactions
