# A2A Commerce Platform

Agent-to-agent commerce infrastructure: billing, payments, marketplace, trust scoring, and paywall enforcement — exposed via HTTP gateway and Python SDK.

## Architecture

```
Agent → SDK (httpx) → Gateway (Starlette + Uvicorn)
                         ├── GET  /health
                         ├── GET  /pricing
                         ├── GET  /pricing/{tool}
                         └── POST /execute
                               ├── billing.*    (wallet, usage tracking)
                               ├── payments.*   (intents, escrow)
                               ├── marketplace.*(search, discovery)
                               └── trust.*      (score lookup)
```

## Quickstart

### 1. Start the Gateway

```bash
python gateway/main.py
```

The gateway starts on `http://localhost:8000` by default. Override with `HOST` and `PORT` env vars.

### 2. Verify

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","tools":13}

curl http://localhost:8000/pricing
# Full tool catalog with pricing, schemas, and tier requirements
```

### 3. Create an API Key

API keys are managed through the paywall system. See `products/paywall/` for key management.

### 4. Execute a Tool

```bash
curl -X POST http://localhost:8000/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_balance","params":{"agent_id":"my-agent"}}'
```

Response:
```json
{"success": true, "result": {"balance": 100.0}, "charged": 0.0}
```

## Python SDK

```python
from sdk.src.a2a_client import A2AClient

async with A2AClient("http://localhost:8000", api_key="a2a_free_...") as client:
    # Health check
    health = await client.health()

    # Get wallet balance
    balance = await client.get_balance("my-agent")

    # Search marketplace
    services = await client.search_services(query="analytics")

    # Create payment
    intent = await client.create_payment_intent(
        payer="my-agent", payee="service-provider", amount=10.0
    )

    # Capture payment
    settlement = await client.capture_payment(intent["id"])
```

### SDK Convenience Methods

| Method | Tool | Description |
|--------|------|-------------|
| `get_balance(agent_id)` | `get_balance` | Wallet balance |
| `deposit(agent_id, amount)` | `deposit` | Add credits |
| `get_usage_summary(agent_id)` | `get_usage_summary` | Usage stats |
| `create_payment_intent(...)` | `create_intent` | Create payment |
| `capture_payment(intent_id)` | `capture_intent` | Settle payment |
| `create_escrow(...)` | `create_escrow` | Hold funds (pro) |
| `release_escrow(escrow_id)` | `release_escrow` | Release escrow (pro) |
| `search_services(...)` | `search_services` | Marketplace search |
| `best_match(query)` | `best_match` | Ranked matching |
| `get_trust_score(server_id)` | `get_trust_score` | Trust score |
| `get_payment_history(agent_id)` | `get_payment_history` | Payment log |

## Available Tools

| Tool | Service | Cost | Tier |
|------|---------|------|------|
| `get_balance` | billing | Free | free |
| `get_usage_summary` | billing | Free | free |
| `deposit` | billing | Free | free |
| `create_intent` | payments | 0.5 | free |
| `capture_intent` | payments | 0.5 | free |
| `create_escrow` | payments | 1.0 | pro |
| `release_escrow` | payments | 0.5 | pro |
| `search_services` | marketplace | Free | free |
| `best_match` | marketplace | 0.1 | free |
| `register_service` | marketplace | Free | pro |
| `get_trust_score` | trust | Free | free |
| `search_servers` | trust | Free | free |
| `get_payment_history` | payments | Free | free |

## Running Tests

```bash
# Gateway tests (20 tests)
cd gateway && python3 -m pytest tests/ -q

# SDK tests (11 tests)
cd sdk && python3 -m pytest tests/ -q

# All existing product tests (987 tests)
python3 -m pytest products/ -q
```

## Examples

- `examples/workflow_trading_agent.py` — discover, price check, execute
- `examples/workflow_data_pipeline.py` — multi-tool chained payments
- `examples/demo_autonomous_agent.py` — full autonomous loop

## Products

| Product | Description |
|---------|-------------|
| `products/billing/` | Usage tracking, wallets, rate policies |
| `products/paywall/` | API key management, tier enforcement |
| `products/payments/` | Payment intents, escrow, subscriptions |
| `products/marketplace/` | Service registry, discovery, matching |
| `products/trust/` | Trust scoring, reputation |
| `products/shared/` | Common error types, audit logging |
