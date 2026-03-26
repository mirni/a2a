# Agent-to-Agent Service Marketplace

Agent-native service marketplace for discovery, matching, and transacting. Agents can register services with structured metadata and other agents can search, filter, and auto-select providers.

## Components

| Component | Description |
|-----------|-------------|
| `Marketplace` | Main API for registration, discovery, and matching |
| `MarketplaceStorage` | SQLite persistence for services, tools, and tags |

## Quick Start

```python
from src.marketplace import Marketplace
from src.storage import MarketplaceStorage

storage = MarketplaceStorage("sqlite:///marketplace.db")
await storage.connect()
marketplace = Marketplace(storage=storage)
```

## Register a Service

```python
from src.models import ServiceCreate, PricingModel, PricingModelType, SLA

spec = ServiceCreate(
    provider_id="data-agent-1",
    name="Real-Time Market Data",
    description="Live price feeds for 500+ crypto pairs",
    category="market-data",
    tools=["get_price", "get_orderbook", "get_trades"],
    pricing=PricingModel(model=PricingModelType.PER_CALL, cost=0.5),
    sla=SLA(uptime=99.9, max_latency_ms=200),
    tags=["crypto", "real-time"],
    endpoint="https://my-mcp-server.com",
)
service = await marketplace.register_service(spec)
```

## Discover Services

```python
from src.models import ServiceSearchParams

# Search by category
results = await marketplace.search(category="market-data")

# Search with filters
params = ServiceSearchParams(
    query="crypto price",
    min_trust_score=70,
    max_cost=1.0,
    sort_by="trust_score",
)
results = await marketplace.search(params)
```

## Auto-Select Best Provider

```python
from src.models import MatchPreference

matches = await marketplace.best_match(
    query="crypto orderbook data",
    budget=1.0,
    min_trust_score=60,
    prefer=MatchPreference.COST,
)
# Returns ranked list with scores and match reasons
```

## Trust Integration

```python
async def get_trust(provider_id: str) -> float:
    return await trust_api.get_score(provider_id)

marketplace = Marketplace(storage=storage, trust_provider=get_trust)
# All search results now include live trust scores
```
