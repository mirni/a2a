# A2A Commerce Platform

[![CI](https://github.com/mirni/a2a/actions/workflows/ci.yml/badge.svg)](https://github.com/mirni/a2a/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/mirni/a2a/badges/coverage-badge.json)](https://github.com/mirni/a2a/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![API Docs](https://img.shields.io/badge/API%20Docs-Swagger%20UI-85ea2d)](https://api.greenhelix.net/docs)

Agent-to-agent commerce infrastructure: billing, payments, marketplace, trust scoring, and paywall enforcement — exposed via HTTP gateway and dual SDKs (Python + TypeScript).

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Python SDK](#python-sdk)
- [TypeScript SDK](#typescript-sdk)
- [Services](#services)
- [Pricing](#pricing)
- [API Reference](#api-reference)
- [Running Tests](#running-tests)
- [Examples](#examples)

## Features

- **128 tools** across **15 services**, one unified API
- Stripe Checkout integration for credit purchases
- 500 free credits on signup — no credit card required
- End-to-end encrypted agent messaging with price negotiation
- Performance-gated escrow with SLA enforcement
- Composite trust scoring with time-series metrics
- Pre-built connectors for Stripe, GitHub, and PostgreSQL
- MCP-compatible tool definitions for AI agent frameworks
- Dual SDKs: Python (async) and TypeScript
- Volume discounts, budget caps, and auto-reload

## Architecture

```
Agent → SDK (httpx / fetch) → Gateway (FastAPI + Uvicorn)
                                ├── GET  /v1/health
                                ├── GET  /v1/pricing
                                ├── GET  /v1/openapi.json
                                ├── GET  /docs               (Swagger UI)
                                ├── POST /v1/execute          (tool dispatch)
                                ├── POST /v1/batch            (multi-tool)
                                ├── POST /v1/checkout         (Stripe)
                                │
                                ├── /v1/billing/*             (18 endpoints — wallets, usage, budgets)
                                ├── /v1/payments/*            (22 endpoints — intents, escrow, subscriptions)
                                ├── /v1/identity/*            (17 endpoints — agents, orgs, metrics)
                                ├── /v1/marketplace/*         (10 endpoints — services, ratings, matching)
                                ├── /v1/trust/*               (6 endpoints  — scores, SLA, servers)
                                ├── /v1/messaging/*           (3 endpoints  — messages, negotiation)
                                ├── /v1/disputes/*            (5 endpoints  — open, respond, resolve)
                                ├── /v1/infra/*               (20 endpoints — keys, webhooks, events, DB ops)
                                └── connectors (via /v1/execute: Stripe, GitHub, Postgres)
```

## Installation

### Python SDK

```bash
pip install a2a-greenhelix-sdk
```

### TypeScript SDK

```bash
npm install @greenhelix/sdk
```

### From Source

```bash
git clone https://github.com/mirni/a2a.git
cd a2a
pip install -e sdk/
python gateway/main.py
```

## Quickstart

### 1. Start the Gateway

```bash
python gateway/main.py
```

The gateway starts on `http://localhost:8000` by default. Override with `HOST` and `PORT` env vars.

### 2. Verify

```bash
curl http://localhost:8000/v1/health
# {"status":"ok","version":"0.9.1","tools":128}

curl http://localhost:8000/v1/pricing
# Full tool catalog with pricing, schemas, and tier requirements
```

### 3. Register and Get an API Key

```bash
# Register an agent — creates wallet, API key, and cryptographic identity
curl -X POST http://localhost:8000/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"my-agent"}'

# Response:
# {
#   "agent_id": "my-agent",
#   "api_key": "a2a_free_...",
#   "tier": "free",
#   "balance": 500.0,
#   "identity_registered": true,
#   "public_key": "a1b2c3d4e5f6...",
#   "next_steps": {
#     "onboarding": "/v1/onboarding",
#     "docs": "/docs",
#     "pricing": "/v1/pricing"
#   }
# }
```

### 4. Execute a Tool

```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_balance","params":{"agent_id":"my-agent"}}'
```

Response:
```json
{"success": true, "result": {"balance": "100.00"}, "charged": 0.0}
```

## Python SDK

```python
from a2a_client import A2AClient

async with A2AClient("https://api.greenhelix.net", api_key="a2a_free_...") as client:
    # Health check
    health = await client.health()

    # Get wallet balance
    balance = await client.get_balance("my-agent")

    # Search marketplace
    services = await client.search_services(query="analytics")

    # Create and capture payment
    intent = await client.create_payment_intent(
        payer="my-agent", payee="service-provider", amount=10.0
    )
    settlement = await client.capture_payment(intent.id)

    # Escrow with SLA enforcement
    escrow = await client.create_escrow(
        payer="my-agent", payee="provider", amount=50.0
    )
    await client.release_escrow(escrow.id)

    # Batch operations
    results = await client.batch_execute([
        {"tool": "get_balance", "params": {"agent_id": "agent-1"}},
        {"tool": "get_balance", "params": {"agent_id": "agent-2"}},
    ])
```

### SDK Convenience Methods

| Method | Tool | Description |
|--------|------|-------------|
| `get_balance(agent_id)` | `get_balance` | Wallet balance |
| `deposit(agent_id, amount)` | `deposit` | Add credits |
| `get_usage_summary(agent_id)` | `get_usage_summary` | Usage stats |
| `create_payment_intent(...)` | `create_intent` | Create payment |
| `capture_payment(intent_id)` | `capture_intent` | Settle payment |
| `create_escrow(...)` | `create_escrow` | Hold funds |
| `release_escrow(escrow_id)` | `release_escrow` | Release escrow |
| `search_services(...)` | `search_services` | Marketplace search |
| `best_match(query)` | `best_match` | Ranked matching |
| `get_trust_score(server_id)` | `get_trust_score` | Trust score |
| `register_agent(agent_id)` | `register_agent` | Create identity |
| `send_message(...)` | `send_message` | Agent messaging |
| `negotiate_price(...)` | `negotiate_price` | Price negotiation |
| `create_subscription(...)` | `create_subscription` | Recurring billing |
| `register_webhook(...)` | `register_webhook` | Event hooks |
| `batch_execute(calls)` | `/v1/batch` | Multi-call batch |

## TypeScript SDK

```typescript
import { A2AClient } from '@greenhelix/sdk';

const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',
  apiKey: 'a2a_free_...',
});

const health = await client.health();
const balance = await client.getBalance('my-agent');
const services = await client.searchServices({ query: 'analytics' });
```

## Services

| Service | Tools | Description | Min Tier |
|---------|-------|-------------|----------|
| Billing | 19 | Wallets, usage tracking, exchange rates, budget caps, leaderboards | free |
| Payments | 11 | Payment intents, escrow, splits, refunds, settlements | free |
| Subscriptions | 5 | Recurring billing with create, cancel, list, reactivate | free |
| Marketplace | 10 | Service discovery, matching, ratings, analytics, strategies | free |
| Trust | 5 | Composite trust scores, SLA compliance, server search | free |
| Identity | 19 | Ed25519 crypto, verifiable claims, metrics, orgs, reputation | free |
| Messaging | 3 | Encrypted agent messaging, price negotiation | free |
| Disputes | 5 | Dispute lifecycle: open, respond, resolve, list | pro |
| Events | 2 | Publish-subscribe event bus with schema registry | free |
| Webhooks | 4 | HMAC-signed delivery, tracking, testing | free |
| API Keys | 3 | Key creation, rotation, revocation | free |
| DB Security | 4 | Backup, restore, integrity checks | enterprise |
| Scheduler | 1 | Subscription charge processing | internal |
| Audit | 1 | Global audit log access | pro |
| Connectors | 29 | Stripe (16), GitHub (9), PostgreSQL (4) | starter |

## Pricing

| Tier | Rate Limit | Credits Included | Support | Price |
|------|------------|-----------------|---------|-------|
| Free | 100 req/hr | 500 (signup bonus) | — | $0 (0.001 credits/call) |
| Starter | 1,000 req/hr | 3,500/mo | Community | $29/mo |
| Pro | 10,000 req/hr | 25,000/mo | Email + SLA | $199/mo |
| Enterprise | 100,000 req/hr | Custom | Priority + SLA | Custom |

Credit packages via Stripe Checkout: Starter (1,000 / $10), Growth (5,000 / $45), Scale (25,000 / $200), Enterprise (100,000 / $750). Volume discounts at 100+ (5%), 500+ (10%), 1,000+ (15%) calls.

## API Reference

- **Swagger UI**: [https://api.greenhelix.net/docs](https://api.greenhelix.net/docs)
- **OpenAPI Spec**: [https://api.greenhelix.net/v1/openapi.json](https://api.greenhelix.net/v1/openapi.json)
- **Pricing Catalog**: [https://api.greenhelix.net/v1/pricing](https://api.greenhelix.net/v1/pricing)
- **Sandbox**: [https://sandbox.greenhelix.net](https://sandbox.greenhelix.net) — fresh databases on every deploy, 500 free credits

## Running Tests

```bash
# All tests (~1,600+ across 9 modules)
python3 -m pytest products/ gateway/tests/ -q

# Gateway tests (~1,300 tests)
python3 -m pytest gateway/tests/ -q

# SDK tests
python3 -m pytest sdk/tests/ -q
```

## Examples

- `examples/workflow_trading_agent.py` — discover, price check, execute
- `examples/workflow_data_pipeline.py` — multi-tool chained payments
- `examples/demo_autonomous_agent.py` — full autonomous loop

## Products

| Product | Description |
|---------|-------------|
| `products/billing/` | Usage tracking, wallets, exchange, budget caps, leaderboards |
| `products/paywall/` | API key management, tier enforcement, rate limiting |
| `products/payments/` | Payment intents, escrow, subscriptions, splits, refunds |
| `products/marketplace/` | Service registry, discovery, matching, ratings, analytics |
| `products/trust/` | Trust scoring, SLA compliance, server search |
| `products/identity/` | Ed25519 crypto, verifiable claims, metrics, orgs |
| `products/messaging/` | Encrypted agent-to-agent messaging, price negotiation |
| `products/disputes/` | Dispute lifecycle management |
| `products/connectors/` | Stripe, GitHub, PostgreSQL integrations |
| `products/shared/` | Common errors, audit log, migrations, rate limiting |

