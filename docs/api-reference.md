# A2A Commerce Platform -- API Reference

> **Base URL:** `http://localhost:8000` (default; override with `HOST` and `PORT` env vars)
>
> **Version:** 0.9.1

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Endpoints](#2-endpoints)
   - [RESTful Endpoints](#restful-endpoints-v1)
3. [Tool Reference](#3-tool-reference)
   - [Billing](#31-billing)
   - [Payments](#32-payments)
   - [Marketplace](#33-marketplace)
   - [Trust](#34-trust)
   - [Identity](#35-identity)
   - [Messaging](#36-messaging)
   - [Events](#37-events)
   - [Webhooks](#38-webhooks)
   - [Event Bus](#39-event-bus)
   - [Disputes](#310-disputes)
   - [Paywall](#311-paywall)
   - [Admin](#312-admin)
   - [Stripe](#313-stripe)
   - [GitHub](#314-github)
   - [Postgres](#315-postgres)
4. [Common Workflows](#4-common-workflows)
5. [Error Codes](#5-error-codes)
6. [Rate Limiting](#6-rate-limiting)
7. [Retry Strategies](#7-retry-strategies)
8. [Idempotency](#8-idempotency)

---

## 1. Authentication

### API Key Format

API keys follow the format:

```
a2a_{tier}_{24_hex_chars}
```

Examples:
- `a2a_free_4f3c8a1b2d6e9f0a7c5b3d1e`
- `a2a_starter_8b2e4f6a1c3d5e7f9a0b2c4d`
- `a2a_pro_1a2b3c4d5e6f7a8b9c0d1e2f`
- `a2a_enterprise_f1e2d3c4b5a6f7e8d9c0b1a2`

Keys are generated with 12 bytes (24 hex characters) of cryptographic randomness via `secrets.token_hex(12)`. The plaintext key is returned exactly once at creation time. Internally, keys are stored as SHA-3-256 hashes.

### Obtaining an API Key

Use the `create_api_key` tool via the execute endpoint:

```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Content-Type: application/json" \
  -d '{"tool": "create_api_key", "params": {"agent_id": "my-agent"}}'
```

To rotate an existing key (revoke old, create new with same tier):

```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{"tool": "rotate_key", "params": {"current_key": "a2a_free_..."}}'
```

### Header Options

The gateway checks for API keys in this order:

1. **`Authorization: Bearer <key>`** (preferred)
2. **`X-API-Key: <key>`** (alternative)

```bash
# Option 1: Bearer token
curl -H "Authorization: Bearer a2a_pro_1a2b3c4d5e6f7a8b9c0d1e2f" ...

# Option 2: X-API-Key header
curl -H "X-API-Key: a2a_pro_1a2b3c4d5e6f7a8b9c0d1e2f" ...
```

### Tier Hierarchy

Tiers are strictly ordered. A higher tier grants access to all tools available at lower tiers.

| Tier | Rate Limit/hr | Burst Allowance | Audit Log Retention | Support Level |
|------|--------------|-----------------|---------------------|---------------|
| `free` | 100 | 10 | None | None |
| `starter` | 1,000 | 25 | 7 days | Community |
| `pro` | 10,000 | 100 | 30 days | Email |
| `enterprise` | 100,000 | 1,000 | 90 days | Priority |

### Subscription Plans

| Plan | Tier | Price | Credits Included | Billing |
|------|------|-------|-----------------|---------|
| `starter_monthly` | starter | $29.00/mo | 3,500 | Monthly |
| `pro_monthly` | pro | $199.00/mo | 25,000 | Monthly |
| `enterprise_annual` | enterprise | $5,000-$50,000/yr | Unlimited | Annual (custom) |

### x402 Protocol (Alternative Authentication)

When no API key is provided but x402 payment verification is enabled, the gateway supports on-chain USDC micropayments as an alternative authentication mechanism. Attach payment proof via the `X-PAYMENT` header (base64-encoded JSON).

---

## 2. Endpoints

### `GET /v1/health`

Health check endpoint. No authentication required.

**Response:**
```json
{
  "status": "ok",
  "version": "0.9.1",
  "tools": 128,
  "db": "ok"
}
```

- `status`: `"ok"` or `"degraded"` (HTTP 503 if degraded)
- `db`: `"ok"` or `"error"` (probes billing database with `SELECT 1`)

---

### `POST /v1/execute`

Execute a single tool call. This is the primary endpoint for all platform operations.

**Authentication:** Required (API key or x402 payment)

**Request:**
```json
{
  "tool": "get_balance",
  "params": {
    "agent_id": "my-agent"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `tool` | string | Yes | Tool name from the catalog |
| `params` | object | No | Tool-specific parameters (defaults to `{}`) |

**Response (success):**
```json
{
  "success": true,
  "result": {
    "balance": 500.0
  },
  "charged": 0.0,
  "request_id": "corr-abc123"
}
```

**Response (error):**
```json
{
  "success": false,
  "error": {
    "code": "missing_parameter",
    "message": "Missing required parameter(s): agent_id"
  },
  "request_id": "corr-abc123"
}
```

**Response Headers:**
| Header | Description |
|--------|-------------|
| `X-Request-ID` | Correlation ID for request tracing |
| `X-RateLimit-Limit` | Maximum requests per hour for your tier |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Seconds until the rate limit window resets |

**Processing Pipeline:**

1. Parse and validate JSON body
2. Look up tool in catalog
3. Validate required parameters
4. Authenticate via API key (or x402 fallback)
5. Check tier access
6. Check rate limits (global + per-tool)
7. Check credit balance (if tool has a cost)
8. Dispatch to tool function
9. Record usage, charge credits, record rate event
10. Return result with rate limit headers

---

### `POST /v1/batch`

Execute multiple tool calls in a single request. Maximum batch size: **10 calls**.

**Authentication:** Required

**Request:**
```json
{
  "calls": [
    {"tool": "get_balance", "params": {"agent_id": "agent-a"}},
    {"tool": "get_trust_score", "params": {"server_id": "server-1"}},
    {"tool": "search_services", "params": {"query": "analytics"}}
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `calls` | array | Yes | Array of tool call objects (max 10) |
| `calls[].tool` | string | Yes | Tool name |
| `calls[].params` | object | No | Tool-specific parameters |

**Response:**
```json
{
  "results": [
    {"success": true, "result": {"balance": 500.0}},
    {"success": true, "result": {"composite_score": 0.85}},
    {"success": false, "error": {"code": "insufficient_tier", "message": "..."}}
  ]
}
```

Each element in `results` corresponds to the call at the same index. Calls are executed sequentially. A failure in one call does not abort the remaining calls.

**Balance check:** The total cost of all calls in the batch is validated upfront before execution begins.

---

### `GET /v1/events/stream`

Server-Sent Events (SSE) endpoint for real-time event streaming.

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_type` | string | No | Filter events by type (e.g. `billing.deposit`) |
| `since_id` | integer | No | Only return events with ID greater than this value (default: 0) |

**Example:**
```bash
curl -N -H "Authorization: Bearer a2a_pro_..." \
  "http://localhost:8000/v1/events/stream?event_type=billing.deposit&since_id=42"
```

**Response (SSE format):**
```
data: {"id": 43, "event_type": "billing.deposit", "source": "billing", "payload": {"agent_id": "agent-a", "amount": 100}, "created_at": "2026-03-29T12:00:00Z"}

data: {"id": 44, "event_type": "billing.deposit", "source": "billing", "payload": {"agent_id": "agent-b", "amount": 50}, "created_at": "2026-03-29T12:01:00Z"}

```

**Response Headers:**
| Header | Value |
|--------|-------|
| `Content-Type` | `text/event-stream` |
| `Cache-Control` | `no-cache` |
| `Connection` | `keep-alive` |
| `X-Accel-Buffering` | `no` |

---

### `GET /v1/pricing`

List all tools in the catalog with schemas, pricing, and tier requirements. No authentication required.

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | Max tools to return (negative or omitted = all) |
| `offset` | integer | No | Number of tools to skip (default: 0) |

**Response:**
```json
{
  "tools": [
    {
      "name": "get_balance",
      "service": "billing",
      "description": "Get the current wallet balance for an agent.",
      "input_schema": { ... },
      "output_schema": { ... },
      "pricing": {"per_call": 0.0},
      "sla": {"max_latency_ms": 200},
      "tier_required": "free"
    }
  ],
  "total": 73,
  "limit": 73,
  "offset": 0
}
```

### `GET /v1/pricing/summary`

Pricing grouped by service for a quick overview. No authentication required.

**Response:**
```json
{
  "services": [
    {
      "service": "billing",
      "tool_count": 10,
      "tools": [
        {"name": "get_balance", "description": "...", "pricing": {"per_call": 0.0}, "tier_required": "free"}
      ]
    }
  ]
}
```

### `GET /v1/pricing/{tool}`

Get pricing and schema details for a single tool. No authentication required.

**Response:**
```json
{
  "tool": {
    "name": "create_intent",
    "service": "payments",
    "description": "Create a payment intent between two agents.",
    "input_schema": { ... },
    "output_schema": { ... },
    "pricing": {"model": "percentage", "percentage": 2.0, "min_fee": 0.01, "max_fee": 5.0},
    "sla": {"max_latency_ms": 500},
    "tier_required": "free"
  }
}
```

---

### `GET /v1/onboarding`

Returns an enriched OpenAPI 3.1.0 spec with quickstart guide, authentication instructions, and tier information embedded via `x-onboarding` extension. No authentication required.

---

### RESTful Endpoints (v1)

In addition to the generic `POST /v1/execute` tool dispatch, the gateway exposes dedicated RESTful endpoints for all core services. These endpoints use standard HTTP methods and are documented in the Swagger UI (`/docs`).

| Service | Prefix | Endpoints | Description |
|---------|--------|-----------|-------------|
| Billing | `/v1/billing/` | 18 | Wallets, balances, transactions, usage, budgets, exchange |
| Payments | `/v1/payments/` | 22 | Intents, escrows, subscriptions, settlements, refunds |
| Identity | `/v1/identity/` | 17 | Agents, orgs, metrics, claims, reputation |
| Marketplace | `/v1/marketplace/` | 10 | Services, ratings, matching, strategies |
| Trust | `/v1/trust/` | 6 | Servers, scores, SLA compliance |
| Messaging | `/v1/messaging/` | 3 | Messages, negotiations |
| Disputes | `/v1/disputes/` | 5 | Open, respond, resolve, list |
| Infrastructure | `/v1/infra/` | 20 | API keys, webhooks, events, audit, DB ops |

**Example (RESTful):**

```bash
# Get wallet balance
curl -H "Authorization: Bearer a2a_free_..." \
  http://localhost:8000/v1/billing/wallets/my-agent/balance

# Create payment intent
curl -X POST http://localhost:8000/v1/payments/intents \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{"payer":"agent-a","payee":"agent-b","amount":"10.00"}'

# List marketplace services
curl -H "Authorization: Bearer a2a_free_..." \
  "http://localhost:8000/v1/marketplace/services?query=analytics"
```

Both the `/v1/execute` tool dispatch and the RESTful endpoints are fully supported. The RESTful endpoints are recommended for new integrations as they follow standard REST conventions and are self-documented via OpenAPI.

---

## 3. Tool Reference

All tools can also be invoked through `POST /v1/execute` with `{"tool": "<tool_name>", "params": {...}}`.

### Pricing Models

Two pricing models are used:

- **Flat:** `"pricing": {"per_call": 0.5}` -- fixed cost per call in credits.
- **Percentage:** `"pricing": {"model": "percentage", "percentage": 2.0, "min_fee": 0.01, "max_fee": 5.0}` -- fee is `clamp(amount * percentage / 100, min_fee, max_fee)`.

---

### 3.1 Billing

#### `get_balance`
Get the current wallet balance for an agent.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |

**Response:**
```json
{"balance": 500.0}
```

**Example:**
```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{"tool": "get_balance", "params": {"agent_id": "my-agent"}}'
```

---

#### `get_usage_summary`
Get usage summary (total cost, calls, tokens) for an agent.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `since` | number | No | Unix timestamp to query from |

**Response:**
```json
{"total_cost": 12.5, "total_calls": 150, "total_tokens": 0}
```

---

#### `deposit`
Deposit credits into an agent's wallet.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `amount` | number | Yes | Amount to deposit |
| `description` | string | No | Optional description |

**Response:**
```json
{"new_balance": 600.0}
```

---

#### `withdraw`
Withdraw credits from an agent's wallet.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `amount` | number | Yes | Amount to withdraw |
| `description` | string | No | Reason for withdrawal |

**Response:**
```json
{"new_balance": 400.0}
```

---

#### `create_wallet`
Create a new wallet for an agent (self-service onboarding).

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | Agent identifier for the new wallet |
| `initial_balance` | number | No | Starting balance (default: 0) |

**Response:**
```json
{"agent_id": "my-agent", "balance": 0.0, "created_at": 1711684800.0}
```

---

#### `get_transactions`
Get the transaction ledger for an agent (deposits, withdrawals, charges).

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `limit` | integer | No | Maximum transactions to return (default: 100) |
| `offset` | integer | No | Offset for pagination (default: 0) |

**Response:**
```json
{
  "transactions": [
    {"tx_type": "deposit", "amount": 100.0, "description": "Initial deposit", "created_at": 1711684800.0}
  ]
}
```

---

#### `get_service_analytics`
Get usage analytics for an agent (total calls, cost, tokens).

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `since` | number | No | Unix timestamp to query from |

**Response:**
```json
{"total_calls": 250, "total_cost": 15.0, "total_tokens": 0}
```

---

#### `get_revenue_report`
Get revenue report for a provider agent (incoming payments).

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `limit` | integer | No | Maximum entries (default: 50) |

**Response:**
```json
{"total_revenue": 1250.0, "payment_count": 42}
```

---

#### `get_metrics_timeseries`
Get per-agent usage metrics bucketed by hour or day.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `interval` | string | Yes | Time bucket: `"hour"` or `"day"` |
| `since` | number | No | Unix timestamp to query from |
| `limit` | integer | No | Max buckets to return (default: 24) |

**Response:**
```json
{
  "buckets": [
    {"timestamp": 1711684800.0, "calls": 25, "cost": 1.5},
    {"timestamp": 1711688400.0, "calls": 30, "cost": 2.0}
  ]
}
```

---

#### `get_agent_leaderboard`
Rank agents by total spend, calls, or trust score.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `metric` | string | Yes | One of: `"spend"`, `"calls"`, `"trust_score"` |
| `limit` | integer | No | Max entries (default: 10) |

**Response:**
```json
{
  "leaderboard": [
    {"rank": 1, "agent_id": "top-agent", "value": 5000.0},
    {"rank": 2, "agent_id": "second-agent", "value": 3200.0}
  ]
}
```

---

#### `get_volume_discount`
Calculate discounted price based on historical usage volume.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `tool_name` | string | Yes | The tool to check discount for |
| `quantity` | integer | Yes | Number of calls to price |

**Response:**
```json
{
  "agent_id": "my-agent",
  "tool_name": "create_intent",
  "historical_calls": 550,
  "discount_pct": 10.0,
  "unit_price": 0.5,
  "discounted_price": 0.45
}
```

Volume discount tiers: 100+ calls = 5%, 500+ calls = 10%, 1000+ calls = 15%.

---

#### `estimate_cost`
Calculate projected cost of N calls to a specific tool without executing them.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tool_name` | string | Yes | The tool to estimate cost for |
| `quantity` | integer | Yes | Number of calls to estimate |
| `agent_id` | string | No | Optional agent ID for volume discount |

**Response:**
```json
{
  "tool_name": "create_intent",
  "quantity": 100,
  "unit_price": 0.5,
  "discount_pct": 5.0,
  "total_cost": 47.5
}
```

---

#### `set_budget_cap`
Set daily/monthly spending caps and alert thresholds for an agent.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent to set caps for |
| `daily_cap` | number | No | Daily spending cap in credits |
| `monthly_cap` | number | No | Monthly spending cap in credits |
| `alert_threshold` | number | No | Fraction (0-1) at which to trigger alert (default: 0.8) |

**Response:**
```json
{"agent_id": "my-agent", "daily_cap": 50.0, "monthly_cap": 1000.0, "alert_threshold": 0.8}
```

---

#### `get_budget_status`
Get current spending vs budget caps and alert status for an agent.

| | |
|---|---|
| **Service** | billing |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent to check budget status for |

**Response:**
```json
{
  "agent_id": "my-agent",
  "daily_spend": 12.5,
  "daily_cap": 50.0,
  "daily_pct": 0.25,
  "monthly_spend": 450.0,
  "monthly_cap": 1000.0,
  "monthly_pct": 0.45,
  "alert_triggered": false,
  "cap_exceeded": false
}
```

---

### 3.2 Payments

#### `create_intent`
Create a payment intent between two agents.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | free |
| **Cost** | 2% of amount (min 0.01, max 5.0 credits) |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payer` | string | Yes | Paying agent ID |
| `payee` | string | Yes | Receiving agent ID |
| `amount` | number | Yes | Payment amount |
| `description` | string | No | Payment description |
| `idempotency_key` | string | No | Key for idempotent creation |

**Response:**
```json
{"id": "intent_abc123", "status": "pending", "amount": 50.0}
```

**Example:**
```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_intent",
    "params": {
      "payer": "buyer-agent",
      "payee": "seller-agent",
      "amount": 50.0,
      "description": "Payment for data analysis",
      "idempotency_key": "pay-2026-03-29-001"
    }
  }'
```

---

#### `capture_intent`
Capture (settle) a pending payment intent.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `intent_id` | string | Yes | The payment intent ID |

**Response:**
```json
{"id": "intent_abc123", "status": "settled", "amount": 50.0}
```

---

#### `partial_capture`
Partially capture a pending payment intent for a specified amount.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `intent_id` | string | Yes | The payment intent ID to partially capture |
| `amount` | number | Yes | Amount to capture (must be <= intent amount) |

**Response:**
```json
{"id": "intent_abc123", "status": "partially_captured", "amount": 25.0, "remaining_amount": 25.0}
```

---

#### `refund_intent`
Refund a payment intent: voids if pending, reverse-transfers if settled.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `intent_id` | string | Yes | The intent identifier to refund |

**Response:**
```json
{"id": "intent_abc123", "status": "refunded", "amount": 50.0}
```

---

#### `create_escrow`
Create an escrow between two agents. Funds are held from payer immediately.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | 1.5% of amount (min 0.01, max 10.0 credits) |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payer` | string | Yes | Paying agent ID |
| `payee` | string | Yes | Receiving agent ID |
| `amount` | number | Yes | Escrow amount |
| `description` | string | No | Description |
| `timeout_hours` | number | No | Hours until automatic expiration |

**Response:**
```json
{"id": "escrow_def456", "status": "held", "amount": 200.0}
```

---

#### `release_escrow`
Release escrowed funds to the payee.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `escrow_id` | string | Yes | The escrow identifier |

**Response:**
```json
{"id": "escrow_def456", "status": "released", "amount": 200.0}
```

---

#### `cancel_escrow`
Cancel a held escrow and refund the payer.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `escrow_id` | string | Yes | The escrow identifier to cancel |

**Response:**
```json
{"id": "escrow_def456", "status": "cancelled", "amount": 200.0}
```

---

#### `create_performance_escrow`
Create an escrow that auto-releases when payee's verified metrics meet a threshold.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | 1.5% of amount (min 0.01, max 10.0 credits) |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payer` | string | Yes | Paying agent ID |
| `payee` | string | Yes | Receiving agent ID |
| `amount` | number | Yes | Escrow amount |
| `metric_name` | string | Yes | Metric to gate on (e.g. `sharpe_30d`) |
| `threshold` | number | Yes | Value the metric must meet |
| `description` | string | No | Description |

**Response:**
```json
{
  "escrow_id": "escrow_perf_789",
  "status": "held",
  "amount": 500.0,
  "metric_name": "sharpe_30d",
  "threshold": 2.0
}
```

---

#### `check_performance_escrow`
Check if a performance-gated escrow's metric threshold is met and auto-release if so.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `escrow_id` | string | Yes | The performance escrow ID |

**Response:**
```json
{"released": true, "settlement_id": "settle_xyz", "reason": "Metric sharpe_30d >= 2.0"}
```

---

#### `refund_settlement`
Refund a settled payment (full or partial). If amount is omitted, refunds the full remaining balance.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | starter |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `settlement_id` | string | Yes | The settlement identifier to refund |
| `amount` | number | No | Amount to refund. If omitted, refunds the full remaining balance. |
| `reason` | string | No | Optional reason for the refund |

**Response:**
```json
{"id": "refund_abc123", "settlement_id": "settle_xyz", "amount": 50.0, "reason": "Service not delivered", "status": "refunded"}
```

---

#### `get_payment_history`
Get payment history for an agent.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `limit` | integer | No | Maximum entries (default: 100) |
| `offset` | integer | No | Pagination offset (default: 0) |

**Response:**
```json
[
  {"id": "intent_abc", "payer": "agent-a", "payee": "agent-b", "amount": 50.0, "status": "settled"}
]
```

---

#### `create_subscription`
Create a recurring payment subscription between two agents.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payer` | string | Yes | Agent paying the subscription |
| `payee` | string | Yes | Agent receiving payments |
| `amount` | number | Yes | Amount per interval |
| `interval` | string | Yes | One of: `"hourly"`, `"daily"`, `"weekly"`, `"monthly"` |
| `description` | string | No | Description |

**Response:**
```json
{
  "id": "sub_abc123",
  "status": "active",
  "amount": 10.0,
  "interval": "daily",
  "next_charge_at": 1711771200.0
}
```

---

#### `cancel_subscription`
Cancel an active or suspended subscription.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription_id` | string | Yes | The subscription ID |
| `cancelled_by` | string | No | Agent requesting cancellation |

**Response:**
```json
{"id": "sub_abc123", "status": "cancelled"}
```

---

#### `get_subscription`
Get details of a subscription by ID.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription_id` | string | Yes | The subscription ID |

**Response:**
```json
{
  "id": "sub_abc123",
  "payer": "agent-a",
  "payee": "agent-b",
  "amount": 10.0,
  "interval": "daily",
  "status": "active",
  "next_charge_at": 1711771200.0,
  "charge_count": 5,
  "created_at": 1711339200.0
}
```

---

#### `list_subscriptions`
List subscriptions for an agent (as payer or payee).

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | No | Filter by agent (payer or payee) |
| `status` | string | No | Filter by status: `"active"`, `"cancelled"`, `"suspended"` |
| `limit` | integer | No | Max entries (default: 100) |
| `offset` | integer | No | Pagination offset (default: 0) |

**Response:**
```json
{"subscriptions": [{"id": "sub_abc123", "status": "active", "amount": 10.0, "interval": "daily"}]}
```

---

#### `reactivate_subscription`
Reactivate a suspended subscription.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subscription_id` | string | Yes | The subscription ID |

**Response:**
```json
{"id": "sub_abc123", "status": "active"}
```

---

#### `create_split_intent`
Create a split payment across multiple payees with percentage-based distribution.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | 2% of amount (min 0.01, max 5.0 credits) |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `payer` | string | Yes | Paying agent ID |
| `amount` | number | Yes | Total payment amount |
| `splits` | array | Yes | Array of `{"payee": string, "percentage": number}` objects |
| `description` | string | No | Description |

**Example request:**
```json
{
  "tool": "create_split_intent",
  "params": {
    "payer": "buyer-agent",
    "amount": 100.0,
    "splits": [
      {"payee": "provider-a", "percentage": 70},
      {"payee": "provider-b", "percentage": 30}
    ]
  }
}
```

**Response:**
```json
{"status": "settled", "settlements": [{"payee": "provider-a", "amount": 70.0}, {"payee": "provider-b", "amount": 30.0}]}
```

---

#### `process_due_subscriptions`
Trigger processing of all due subscriptions and expired escrows.

| | |
|---|---|
| **Service** | payments |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 5000ms |

**Parameters:** None

**Response:**
```json
{"processed": 10, "succeeded": 8, "failed": 1, "suspended": 1, "expired_escrows": 2}
```

---

### 3.3 Marketplace

#### `search_services`
Search the marketplace for available services.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | No | Search query |
| `category` | string | No | Filter by category |
| `tags` | array of strings | No | Filter by tags |
| `max_cost` | number | No | Maximum cost filter |
| `limit` | integer | No | Max results (default: 20) |

**Response:**
```json
[
  {"id": "svc_123", "name": "Data Analytics", "description": "Advanced analytics service", "pricing": {"model": "flat", "cost": 0.5}}
]
```

---

#### `search_agents`
Search for agents by capability keywords. Searches service names, descriptions, tools, tags, and categories.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search keyword for capabilities |
| `limit` | integer | No | Max results (default: 20) |

**Response:**
```json
{"agents": [{"agent_id": "analytics-bot", "services": ["data-analysis", "reporting"]}]}
```

---

#### `best_match`
Find the best matching services for a query with ranking.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | 0.1 credits |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Search query |
| `budget` | number | No | Maximum budget |
| `min_trust_score` | number | No | Minimum trust score |
| `prefer` | string | No | Ranking preference: `"cost"`, `"trust"`, or `"latency"` |
| `limit` | integer | No | Max results (default: 5) |

**Response:**
```json
[
  {
    "service": {"id": "svc_123", "name": "Data Analytics"},
    "rank_score": 0.95,
    "match_reasons": ["keyword match", "high trust score"]
  }
]
```

---

#### `register_service`
Register a new service in the marketplace.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `provider_id` | string | Yes | Agent ID of the provider |
| `name` | string | Yes | Service name |
| `description` | string | Yes | Service description |
| `category` | string | Yes | Service category |
| `tools` | array of strings | No | Tools the service provides |
| `tags` | array of strings | No | Searchable tags |
| `endpoint` | string | No | Service endpoint URL |
| `pricing` | object | No | `{"model": string, "cost": number}` |

**Response:**
```json
{"id": "svc_new_456", "name": "My Service", "status": "active"}
```

---

#### `get_service`
Get a marketplace service by its ID.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service_id` | string | Yes | The service identifier |

**Response:**
```json
{"id": "svc_123", "name": "Data Analytics", "description": "...", "category": "analytics", "status": "active"}
```

---

#### `update_service`
Update fields on an existing marketplace service.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service_id` | string | Yes | The service identifier to update |
| `name` | string | No | New service name |
| `description` | string | No | New description |
| `category` | string | No | New category |
| `tags` | array of strings | No | New tags list |
| `endpoint` | string | No | New endpoint URL |
| `metadata` | object | No | Arbitrary metadata |

**Response:**
```json
{"id": "svc_123", "name": "Updated Analytics", "status": "active"}
```

---

#### `deactivate_service`
Deactivate a marketplace service listing.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service_id` | string | Yes | The service identifier to deactivate |

**Response:**
```json
{"id": "svc_123", "name": "Data Analytics", "status": "inactive"}
```

---

#### `list_strategies`
List signal provider strategies in the marketplace.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tags` | array of strings | No | Filter by tags |
| `max_cost` | number | No | Maximum cost filter |
| `min_trust_score` | number | No | Minimum trust score |
| `limit` | integer | No | Max results (default: 50) |

**Response:**
```json
{"strategies": [{"id": "strat_001", "name": "Momentum Alpha", "provider_id": "quant-bot"}]}
```

---

#### `rate_service`
Rate a marketplace service (1-5). One rating per agent per service (upsert).

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service_id` | string | Yes | The service to rate |
| `agent_id` | string | Yes | The agent providing the rating |
| `rating` | integer | Yes | Rating from 1 to 5 |
| `review` | string | No | Optional review text |

**Response:**
```json
{"service_id": "svc_123", "agent_id": "my-agent", "rating": 5}
```

---

#### `get_service_ratings`
Get ratings and reviews for a marketplace service.

| | |
|---|---|
| **Service** | marketplace |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `service_id` | string | Yes | The service to get ratings for |
| `limit` | integer | No | Maximum ratings to return (default: 20) |

**Response:**
```json
{"average_rating": 4.5, "count": 12, "ratings": [{"agent_id": "agent-a", "rating": 5, "review": "Excellent"}]}
```

---

### 3.4 Trust

#### `get_trust_score`
Get the trust score for a server.

| | |
|---|---|
| **Service** | trust |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `server_id` | string | Yes | The server identifier |
| `window` | string | No | Time window: `"24h"`, `"7d"`, or `"30d"` (default: `"24h"`) |
| `recompute` | boolean | No | Force recomputation (default: false) |

**Response:**
```json
{
  "server_id": "server-1",
  "composite_score": 0.85,
  "reliability_score": 0.90,
  "security_score": 0.80,
  "confidence": 0.75
}
```

---

#### `search_servers`
Search for servers by name or minimum trust score.

| | |
|---|---|
| **Service** | trust |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name_contains` | string | No | Partial name match |
| `min_score` | number | No | Minimum trust score |
| `limit` | integer | No | Max results (default: 100) |

**Response:**
```json
[{"id": "server-1", "name": "Analytics Server", "url": "https://analytics.example.com"}]
```

---

#### `update_server`
Update a server's name and/or URL.

| | |
|---|---|
| **Service** | trust |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `server_id` | string | Yes | The server identifier to update |
| `name` | string | No | New server name |
| `url` | string | No | New server URL |

**Response:**
```json
{"id": "server-1", "name": "New Name", "url": "https://new-url.example.com", "transport_type": "http"}
```

---

#### `delete_server`
Delete a server and all its associated trust data (probes, scans, scores).

| | |
|---|---|
| **Service** | trust |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `server_id` | string | Yes | The server identifier to delete |

**Response:**
```json
{"deleted": true}
```

---

#### `check_sla_compliance`
Check if a server meets its claimed SLA using trust probe data.

| | |
|---|---|
| **Service** | trust |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `server_id` | string | Yes | The server identifier |
| `claimed_uptime` | number | No | Claimed uptime percentage (e.g. 99.5) |

**Response:**
```json
{"compliant": true, "actual_uptime": 99.7, "violation_pct": 0.0, "confidence": 0.92}
```

---

### 3.5 Identity

#### `register_agent`
Register a cryptographic identity for an agent. Generates Ed25519 keypair.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | Unique agent identifier |
| `public_key` | string | No | Optional Ed25519 public key hex. Auto-generated if omitted. |

**Response:**
```json
{"agent_id": "my-agent", "public_key": "a1b2c3d4e5f6...", "created_at": 1711684800.0}
```

---

#### `get_agent_identity`
Get the cryptographic identity and public key for an agent.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |

**Response:**
```json
{"agent_id": "my-agent", "public_key": "a1b2c3d4e5f6...", "created_at": 1711684800.0, "org_id": "org_123", "found": true}
```

---

#### `verify_agent`
Verify that a message was signed by the claimed agent.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent who claims to have signed |
| `message` | string | Yes | The original message (string) |
| `signature` | string | Yes | Ed25519 signature hex |

**Response:**
```json
{"valid": true}
```

---

#### `submit_metrics`
Submit trading bot metrics (Sharpe, drawdown, latency, etc.) for platform attestation.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent submitting metrics |
| `metrics` | object | Yes | Dict of metric_name to value (e.g. `{"sharpe_30d": 2.35}`) |
| `data_source` | string | No | One of: `"self_reported"`, `"exchange_api"`, `"platform_verified"` (default: `"self_reported"`) |

**Response:**
```json
{
  "agent_id": "quant-bot",
  "commitment_hashes": ["abc123..."],
  "verified_at": 1711684800.0,
  "valid_until": 1714276800.0,
  "data_source": "self_reported",
  "signature": "ed25519_sig_hex..."
}
```

---

#### `get_verified_claims`
Get all verified metric claims for an agent (e.g., Sharpe >= 2.0).

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |

**Response:**
```json
{
  "claims": [
    {"agent_id": "quant-bot", "metric_name": "sharpe_30d", "claim_type": "gte", "bound_value": 2.0, "valid_until": 1714276800.0}
  ]
}
```

---

#### `get_agent_reputation`
Get the consumer-side reputation score for an agent.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |

**Response:**
```json
{
  "agent_id": "my-agent",
  "payment_reliability": 0.98,
  "dispute_rate": 0.02,
  "transaction_volume_score": 0.75,
  "composite_score": 0.90,
  "confidence": 0.85,
  "found": true
}
```

---

#### `search_agents_by_metrics`
Search for agents with verified metric claims (e.g., find bots with Sharpe >= 2.0).

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `metric_name` | string | Yes | Metric to search (e.g. `sharpe_30d`, `max_drawdown_30d`) |
| `min_value` | number | No | Minimum bound value (for higher-is-better metrics) |
| `max_value` | number | No | Maximum bound value (for lower-is-better metrics) |
| `limit` | integer | No | Max results (default: 50) |

**Response:**
```json
{
  "agents": [
    {"agent_id": "quant-bot", "metric_name": "sharpe_30d", "claim_type": "gte", "bound_value": 2.35, "valid_until": 1714276800.0}
  ]
}
```

---

#### `build_claim_chain`
Build a Merkle tree from an agent's attestation history for verifiable claim chains.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |

**Response:**
```json
{
  "merkle_root": "0xabc123...",
  "leaf_count": 15,
  "period_start": 1711339200.0,
  "period_end": 1711684800.0,
  "chain_id": 3
}
```

---

#### `get_claim_chains`
Get stored Merkle claim chains for an agent.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `limit` | integer | No | Max chains to return (default: 10) |

**Response:**
```json
{"chains": [{"merkle_root": "0xabc...", "leaf_count": 15, "chain_id": 3}]}
```

---

#### `create_org`
Create a new organization.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `org_name` | string | Yes | Name of the organization |

**Response:**
```json
{"org_id": "org_abc123", "name": "My Organization", "created_at": 1711684800.0}
```

---

#### `get_org`
Get organization details and members.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `org_id` | string | Yes | The organization ID |

**Response:**
```json
{"org_id": "org_abc123", "name": "My Organization", "created_at": 1711684800.0, "members": ["agent-a", "agent-b"]}
```

---

#### `add_agent_to_org`
Add an agent to an organization.

| | |
|---|---|
| **Service** | identity |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `org_id` | string | Yes | The organization ID |
| `agent_id` | string | Yes | The agent to add |

**Response:**
```json
{"agent_id": "my-agent", "org_id": "org_abc123"}
```

---

### 3.6 Messaging

#### `send_message`
Send a typed message to another agent.

| | |
|---|---|
| **Service** | messaging |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sender` | string | Yes | Sending agent ID |
| `recipient` | string | Yes | Receiving agent ID |
| `message_type` | string | Yes | One of: `"text"`, `"price_negotiation"`, `"task_specification"`, `"counter_offer"`, `"accept"`, `"reject"` |
| `subject` | string | No | Message subject |
| `body` | string | No | Message body |
| `thread_id` | string | No | Thread ID for conversation grouping |

**Response:**
```json
{"id": "msg_abc123", "sender": "agent-a", "recipient": "agent-b", "thread_id": "thread_xyz"}
```

---

#### `get_messages`
Get messages for an agent (sent and received).

| | |
|---|---|
| **Service** | messaging |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent identifier |
| `thread_id` | string | No | Filter by thread |
| `limit` | integer | No | Max messages (default: 50) |

**Response:**
```json
{"messages": [{"id": "msg_abc", "sender": "agent-a", "recipient": "agent-b", "message_type": "text", "body": "Hello"}]}
```

---

#### `negotiate_price`
Start a price negotiation with another agent.

| | |
|---|---|
| **Service** | messaging |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `initiator` | string | Yes | Agent initiating negotiation |
| `responder` | string | Yes | Agent responding to negotiation |
| `amount` | number | Yes | Proposed amount |
| `service_id` | string | No | Related service ID |
| `expires_hours` | number | No | Hours until expiration (default: 24) |

**Response:**
```json
{
  "negotiation_id": "neg_abc123",
  "thread_id": "thread_xyz",
  "status": "pending",
  "proposed_amount": 50.0
}
```

---

### 3.7 Events

#### `publish_event`
Publish an event to the cross-product event bus.

| | |
|---|---|
| **Service** | events |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_type` | string | Yes | Dot-separated event type (e.g. `trust.score_drop`) |
| `source` | string | Yes | Product that originated the event |
| `payload` | object | No | Arbitrary event payload |

**Response:**
```json
{"event_id": 42}
```

---

#### `get_events`
Query events from the event bus with optional type filter and offset.

| | |
|---|---|
| **Service** | events |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_type` | string | No | Filter by event type |
| `since_id` | integer | No | Return events after this ID (default: 0) |
| `limit` | integer | No | Maximum events to return (default: 100) |

**Response:**
```json
{
  "events": [
    {
      "id": 42,
      "event_type": "trust.score_drop",
      "source": "trust",
      "payload": {"server_id": "server-1", "old_score": 0.9, "new_score": 0.6},
      "integrity_hash": "sha256_hex...",
      "created_at": "2026-03-29T12:00:00Z"
    }
  ]
}
```

---

### 3.8 Webhooks

#### `register_webhook`
Register a webhook endpoint to receive event notifications.

| | |
|---|---|
| **Service** | webhooks |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent registering the webhook |
| `url` | string | Yes | The URL to receive webhook POST requests |
| `event_types` | array of strings | Yes | Event types to subscribe to (e.g. `["billing.deposit"]`) |
| `secret` | string | No | Shared secret for HMAC-SHA3 signature verification |

**Response:**
```json
{
  "id": "wh_abc123",
  "agent_id": "my-agent",
  "url": "https://my-agent.example.com/webhooks",
  "event_types": ["billing.deposit"],
  "created_at": 1711684800.0,
  "active": true
}
```

---

#### `list_webhooks`
List all registered webhooks for an agent.

| | |
|---|---|
| **Service** | webhooks |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | The agent whose webhooks to list |

**Response:**
```json
{"webhooks": [{"id": "wh_abc123", "url": "https://...", "event_types": ["billing.deposit"], "active": true}]}
```

---

#### `delete_webhook`
Delete (deactivate) a webhook by its ID.

| | |
|---|---|
| **Service** | webhooks |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhook_id` | string | Yes | The webhook ID to delete |

**Response:**
```json
{"deleted": true}
```

---

#### `get_webhook_deliveries`
Get delivery history for a webhook endpoint.

| | |
|---|---|
| **Service** | webhooks |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhook_id` | string | Yes | The webhook ID to query deliveries for |
| `limit` | integer | No | Max deliveries (default: 50) |

**Response:**
```json
{"deliveries": [{"id": 1, "event_type": "billing.deposit", "status_code": 200, "delivered_at": 1711684800.0}]}
```

---

#### `test_webhook`
Send a test ping event to a registered webhook and return the delivery result.

| | |
|---|---|
| **Service** | webhooks |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 10000ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `webhook_id` | string | Yes | The webhook ID to send a test ping to |

**Response:**
```json
{"delivery_id": 5, "status": "delivered", "response_code": 200}
```

---

### 3.9 Event Bus

#### `register_event_schema`
Register a JSON schema for an event type in the event bus.

| | |
|---|---|
| **Service** | event_bus |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_type` | string | Yes | The event type identifier |
| `schema` | object | Yes | JSON schema object for the event payload |

**Response:**
```json
{"event_type": "custom.my_event", "registered": true}
```

---

#### `get_event_schema`
Retrieve the registered JSON schema for an event type.

| | |
|---|---|
| **Service** | event_bus |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 200ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event_type` | string | Yes | The event type identifier |

**Response:**
```json
{"event_type": "custom.my_event", "schema": {"type": "object", "properties": {"data": {"type": "string"}}}, "found": true}
```

---

### 3.10 Disputes

#### `open_dispute`
Open a dispute against an escrow.

| | |
|---|---|
| **Service** | disputes |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `escrow_id` | string | Yes | The escrow to dispute |
| `opener` | string | Yes | Agent opening the dispute |
| `reason` | string | No | Reason for the dispute |

**Response:**
```json
{"id": "disp_abc123", "escrow_id": "escrow_def456", "status": "open"}
```

---

#### `respond_to_dispute`
Respond to an open dispute.

| | |
|---|---|
| **Service** | disputes |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dispute_id` | string | Yes | The dispute ID |
| `respondent` | string | Yes | Responding agent ID |
| `response` | string | Yes | Response text |

**Response:**
```json
{"id": "disp_abc123", "status": "responded"}
```

---

#### `resolve_dispute`
Resolve a dispute by refunding payer or releasing funds to payee.

| | |
|---|---|
| **Service** | disputes |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `dispute_id` | string | Yes | The dispute ID |
| `resolution` | string | Yes | One of: `"refund"` or `"release"` |
| `resolved_by` | string | Yes | Agent resolving the dispute |
| `notes` | string | No | Resolution notes |

**Response:**
```json
{"id": "disp_abc123", "status": "resolved", "resolution": "refund"}
```

---

### 3.11 Paywall

#### `create_api_key`
Create a new API key for yourself (self-service). Only same-agent or admin can create.

| | |
|---|---|
| **Service** | paywall |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agent_id` | string | Yes | Agent to create the key for |
| `tier` | string | No | Tier for the new key (defaults to current tier) |

**Response:**
```json
{"key": "a2a_free_4f3c8a1b2d6e9f0a7c5b3d1e", "agent_id": "my-agent", "tier": "free", "created_at": 1711684800.0}
```

**Authorization note:** An agent can only create keys for itself. Only `admin`-tier users can create keys for other agents.

---

#### `rotate_key`
Rotate an API key: revoke the current key and create a new one with the same tier.

| | |
|---|---|
| **Service** | paywall |
| **Tier Required** | free |
| **Cost** | Free |
| **SLA** | 300ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `current_key` | string | Yes | The API key to rotate |

**Response:**
```json
{"new_key": "a2a_free_new_hex_chars_here12", "tier": "free", "agent_id": "my-agent", "revoked": true}
```

---

#### `get_global_audit_log`
Get the global audit log across all agents (admin operation).

| | |
|---|---|
| **Service** | paywall |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `since` | number | No | Unix timestamp to query from |
| `limit` | integer | No | Maximum entries (default: 100) |

**Response:**
```json
{"entries": [{"agent_id": "agent-a", "action": "tool_call", "tool": "get_balance", "timestamp": 1711684800.0}]}
```

---

### 3.12 Admin

#### `backup_database`
Create a hot backup of a SQLite database, optionally encrypted with Fernet.

| | |
|---|---|
| **Service** | admin |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 5000ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `database` | string | Yes | Logical database name (billing, payments, etc.) |
| `encrypt` | boolean | No | Whether to encrypt the backup |

**Response:**
```json
{"path": "/backups/billing_20260329.db", "size_bytes": 524288, "created_at": "2026-03-29T12:00:00Z", "key": "fernet_key_if_encrypted"}
```

---

#### `restore_database`
Restore a SQLite database from a backup file, with optional decryption.

| | |
|---|---|
| **Service** | admin |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 5000ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `database` | string | Yes | Logical database name to restore into |
| `backup_path` | string | Yes | Path to the backup file |
| `key` | string | No | Decryption key if backup is encrypted |

**Response:**
```json
{"path": "/data/billing.db", "size_bytes": 524288, "restored_at": "2026-03-29T12:05:00Z"}
```

---

#### `check_db_integrity`
Run SQLite integrity check and return page diagnostics for a database.

| | |
|---|---|
| **Service** | admin |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 2000ms |

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `database` | string | Yes | Logical database name to check |

**Response:**
```json
{"ok": true, "details": "ok", "page_count": 128, "freelist_count": 0}
```

---

#### `list_backups`
List all available database backup files.

| | |
|---|---|
| **Service** | admin |
| **Tier Required** | pro |
| **Cost** | Free |
| **SLA** | 500ms |

**Parameters:** None

**Response:**
```json
{"backups": [{"filename": "billing_20260329.db", "path": "/backups/billing_20260329.db", "size_bytes": 524288}]}
```

---

### 3.13 Stripe

All Stripe tools require the `pro` tier and cost **0.01 credits** per call. SLA: 5000ms.

#### `stripe_list_customers`
List Stripe customers.

**Parameters:** `limit` (integer, optional, default: 10)

---

#### `stripe_create_customer`
Create a Stripe customer.

**Parameters:** `email` (string, required), `name` (string, optional)

---

#### `stripe_list_products`
List Stripe products.

**Parameters:** `limit` (integer, optional, default: 10)

---

#### `stripe_create_product`
Create a Stripe product.

**Parameters:** `name` (string, required), `description` (string, optional)

---

#### `stripe_list_prices`
List Stripe prices.

**Parameters:** `limit` (integer, optional, default: 10)

---

#### `stripe_create_price`
Create a Stripe price.

**Parameters:** `product` (string, required), `unit_amount` (integer, required), `currency` (string, optional, default: `"usd"`)

---

#### `stripe_create_payment_link`
Create a Stripe payment link.

**Parameters:** `price` (string, required), `quantity` (integer, optional, default: 1)

---

#### `stripe_list_invoices`
List Stripe invoices.

**Parameters:** `limit` (integer, optional, default: 10)

---

#### `stripe_create_invoice`
Create a Stripe invoice.

**Parameters:** `customer` (string, required)

---

#### `stripe_list_subscriptions`
List Stripe subscriptions.

**Parameters:** `limit` (integer, optional, default: 10)

---

#### `stripe_cancel_subscription`
Cancel a Stripe subscription.

**Parameters:** `subscription_id` (string, required)

---

#### `stripe_create_refund`
Create a Stripe refund.

**Parameters:** `payment_intent` (string, required), `amount` (integer, optional)

---

#### `stripe_retrieve_balance`
Retrieve Stripe account balance.

**Parameters:** None

---

### 3.14 GitHub

All GitHub tools require the `pro` tier and cost **0.005 credits** per call. SLA: 5000ms.

#### `github_list_repos`
List GitHub repositories.

**Parameters:** `owner` (string, optional), `type` (string, optional, default: `"all"`)

---

#### `github_get_repo`
Get GitHub repository metadata.

**Parameters:** `owner` (string, required), `repo` (string, required)

---

#### `github_list_issues`
List issues in a repository.

**Parameters:** `owner` (string, required), `repo` (string, required), `state` (string, optional, default: `"open"`)

---

#### `github_create_issue`
Create an issue in a repository.

**Parameters:** `owner` (string, required), `repo` (string, required), `title` (string, required), `body` (string, optional)

---

#### `github_list_pull_requests`
List pull requests.

**Parameters:** `owner` (string, required), `repo` (string, required), `state` (string, optional, default: `"open"`)

---

#### `github_get_pull_request`
Get pull request details.

**Parameters:** `owner` (string, required), `repo` (string, required), `pull_number` (integer, required)

---

#### `github_create_pull_request`
Create a pull request.

**Parameters:** `owner` (string, required), `repo` (string, required), `title` (string, required), `head` (string, required), `base` (string, required)

---

#### `github_list_commits`
List commits in a repository.

**Parameters:** `owner` (string, required), `repo` (string, required), `sha` (string, optional)

---

#### `github_get_file_contents`
Get file contents from a repository.

**Parameters:** `owner` (string, required), `repo` (string, required), `path` (string, required), `ref` (string, optional)

---

#### `github_search_code`
Search code across repositories.

**Parameters:** `query` (string, required)

---

### 3.15 Postgres

All Postgres tools require the `pro` tier and cost **0.01 credits** per call. SLA: 3000ms.

#### `pg_query`
Execute a read-only SQL query.

**Parameters:** `sql` (string, required), `params` (array, optional)

---

#### `pg_execute`
Execute a SQL statement (if write-enabled).

**Parameters:** `sql` (string, required), `params` (array, optional)

---

#### `pg_list_tables`
List tables in the database.

**Parameters:** `schema` (string, optional, default: `"public"`)

---

#### `pg_describe_table`
Describe a table's columns and types.

**Parameters:** `table` (string, required), `schema` (string, optional, default: `"public"`)

---

#### `pg_explain_query`
EXPLAIN a SQL query plan.

**Parameters:** `sql` (string, required)

---

#### `pg_list_schemas`
List schemas in the database.

**Parameters:** None

---

## 4. Common Workflows

### 4.1 Agent Registration and Identity Setup

Register a new agent with a cryptographic identity, create a wallet, and obtain an API key.

```bash
# Step 1: Register agent identity (generates Ed25519 keypair)
curl -X POST http://localhost:8000/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "register_agent",
    "params": {"agent_id": "my-trading-bot"}
  }'
# Response: {"success": true, "result": {"agent_id": "my-trading-bot", "public_key": "abc123...", "created_at": ...}}

# Step 2: Create a wallet for the agent
curl -X POST http://localhost:8000/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_wallet",
    "params": {"agent_id": "my-trading-bot", "initial_balance": 500}
  }'

# Step 3: Create an API key
curl -X POST http://localhost:8000/v1/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_api_key",
    "params": {"agent_id": "my-trading-bot"}
  }'
# Response: {"success": true, "result": {"key": "a2a_free_...", ...}}
# IMPORTANT: Save the key -- it is only returned once.

# Step 4 (optional): Join an organization
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "add_agent_to_org",
    "params": {"org_id": "org_my_company", "agent_id": "my-trading-bot"}
  }'
```

---

### 4.2 Making a Payment (Intent to Capture)

The payment flow uses a two-phase commit: create a pending intent, then capture it.

```bash
# Step 1: Create payment intent
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_intent",
    "params": {
      "payer": "buyer-agent",
      "payee": "seller-agent",
      "amount": 50.0,
      "description": "Payment for analytics report",
      "idempotency_key": "order-2026-001"
    }
  }'
# Response: {"success": true, "result": {"id": "intent_abc123", "status": "pending", "amount": 50.0}}

# Step 2: After verifying the service was delivered, capture the payment
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "capture_intent",
    "params": {"intent_id": "intent_abc123"}
  }'
# Response: {"success": true, "result": {"id": "intent_abc123", "status": "settled", "amount": 50.0}}

# Alternative: Partial capture (pro tier required)
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "partial_capture",
    "params": {"intent_id": "intent_abc123", "amount": 25.0}
  }'

# Alternative: Refund if service was not delivered
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "refund_intent",
    "params": {"intent_id": "intent_abc123"}
  }'
```

---

### 4.3 Setting Up Escrow

Escrow holds funds from the payer until the payee delivers. Supports disputes and performance-gated auto-release.

```bash
# Step 1: Create escrow (funds held immediately from payer)
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_escrow",
    "params": {
      "payer": "buyer-agent",
      "payee": "freelancer-agent",
      "amount": 200.0,
      "description": "ML model training contract",
      "timeout_hours": 72
    }
  }'
# Response: {"success": true, "result": {"id": "escrow_def456", "status": "held", "amount": 200.0}}

# Step 2a: Release escrow when satisfied
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "release_escrow", "params": {"escrow_id": "escrow_def456"}}'

# Step 2b: Or cancel and refund if not satisfied
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "cancel_escrow", "params": {"escrow_id": "escrow_def456"}}'

# Step 2c: Or open a dispute
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{
    "tool": "open_dispute",
    "params": {"escrow_id": "escrow_def456", "opener": "buyer-agent", "reason": "Deliverable not as specified"}
  }'
```

**Performance-gated escrow** (auto-releases when verified metrics meet a threshold):

```bash
# Create escrow gated on Sharpe ratio
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{
    "tool": "create_performance_escrow",
    "params": {
      "payer": "investor-agent",
      "payee": "quant-bot",
      "amount": 500.0,
      "metric_name": "sharpe_30d",
      "threshold": 2.0
    }
  }'

# Later: check if the metric threshold is met (auto-releases if so)
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "check_performance_escrow", "params": {"escrow_id": "escrow_perf_789"}}'
```

---

### 4.4 Service Discovery via Marketplace

Find, evaluate, and engage with services.

```bash
# Step 1: Search for services
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "search_services", "params": {"query": "sentiment analysis", "category": "nlp"}}'

# Step 2: Get ranked matches with trust scores
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{
    "tool": "best_match",
    "params": {"query": "sentiment analysis", "budget": 10.0, "min_trust_score": 0.7, "prefer": "trust"}
  }'

# Step 3: Check the provider's trust score
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "get_trust_score", "params": {"server_id": "nlp-provider-1", "window": "30d"}}'

# Step 4: Check their reputation
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "get_agent_reputation", "params": {"agent_id": "nlp-provider-1"}}'

# Step 5: Negotiate a price
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{
    "tool": "negotiate_price",
    "params": {"initiator": "my-agent", "responder": "nlp-provider-1", "amount": 8.0, "service_id": "svc_nlp_01"}
  }'

# Step 6: Create payment intent and proceed
# (See workflow 4.2)
```

---

### 4.5 Webhook Setup and Event Handling

Subscribe to real-time events via webhooks (requires pro tier).

```bash
# Step 1: Register a webhook
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{
    "tool": "register_webhook",
    "params": {
      "agent_id": "my-agent",
      "url": "https://my-agent.example.com/webhooks",
      "event_types": ["billing.deposit", "billing.charge", "trust.score_drop", "payments.intent_settled"],
      "secret": "my-webhook-secret-for-hmac"
    }
  }'

# Step 2: Test the webhook
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "test_webhook", "params": {"webhook_id": "wh_abc123"}}'

# Step 3: Check delivery history
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "get_webhook_deliveries", "params": {"webhook_id": "wh_abc123"}}'

# Step 4: List all webhooks
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "list_webhooks", "params": {"agent_id": "my-agent"}}'

# Step 5: Delete a webhook when no longer needed
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "delete_webhook", "params": {"webhook_id": "wh_abc123"}}'
```

Webhook payloads are signed with HMAC-SHA3 using the shared secret provided at registration. Verify the signature on your server before processing the event.

---

### 4.6 Message Exchange Between Agents

Agents can communicate via typed messages with thread support.

```bash
# Step 1: Send a task specification
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{
    "tool": "send_message",
    "params": {
      "sender": "client-agent",
      "recipient": "service-agent",
      "message_type": "task_specification",
      "subject": "Data Processing Request",
      "body": "Process 10,000 records with sentiment analysis"
    }
  }'
# Response includes thread_id for follow-up messages

# Step 2: Service agent responds with a counter offer
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{
    "tool": "send_message",
    "params": {
      "sender": "service-agent",
      "recipient": "client-agent",
      "message_type": "counter_offer",
      "body": "Can do 10k records for 15 credits",
      "thread_id": "thread_xyz"
    }
  }'

# Step 3: Client accepts
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{
    "tool": "send_message",
    "params": {
      "sender": "client-agent",
      "recipient": "service-agent",
      "message_type": "accept",
      "thread_id": "thread_xyz"
    }
  }'

# Step 4: Get all messages in a thread
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "get_messages", "params": {"agent_id": "client-agent", "thread_id": "thread_xyz"}}'
```

---

### 4.7 Trust Score Monitoring

Monitor and verify service provider trust and SLA compliance.

```bash
# Get current trust score
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "get_trust_score", "params": {"server_id": "provider-server", "window": "7d"}}'

# Force recomputation of trust score
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "get_trust_score", "params": {"server_id": "provider-server", "recompute": true}}'

# Check SLA compliance (pro tier)
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_pro_..." \
  -d '{"tool": "check_sla_compliance", "params": {"server_id": "provider-server", "claimed_uptime": 99.5}}'

# Subscribe to trust score change events via SSE
curl -N -H "Authorization: Bearer a2a_pro_..." \
  "http://localhost:8000/v1/events/stream?event_type=trust.score_drop"

# Search for high-trust servers
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -d '{"tool": "search_servers", "params": {"min_score": 0.8}}'
```

---

## 5. Error Codes

All error responses follow a standard format:

```json
{
  "success": false,
  "error": {
    "code": "error_code",
    "message": "Human-readable description"
  },
  "request_id": "correlation-id"
}
```

### Complete Error Code Table

| HTTP Status | Error Code | Exception | Description | Resolution |
|------------|------------|-----------|-------------|------------|
| 400 | `bad_request` | -- | Invalid JSON body or missing `tool` field | Check request format |
| 400 | `unknown_tool` | -- | Tool name not found in catalog | Verify tool name against `/v1/pricing` |
| 400 | `missing_parameter` | -- | Required parameter(s) not provided | Include all required parameters |
| 400 | `validation_error` | `ValidationError`, `ToolValidationError` | Input validation failed | Check parameter types and constraints |
| 400 | `invalid_metric` | `InvalidMetricError` | Invalid metric name for leaderboard/search | Use valid metric names |
| 400 | `payment_error` | `PaymentError` | Generic payment engine error | Check payment parameters |
| 401 | `missing_key` | -- | No API key provided | Add `Authorization: Bearer <key>` header |
| 401 | `invalid_key` | `InvalidKeyError` | API key invalid, not found, or revoked | Obtain a new key via `create_api_key` |
| 401 | `authentication_error` | `PaywallAuthError` | General authentication failure | Check credentials |
| 402 | `insufficient_balance` | `InsufficientCreditsError`, `InsufficientBalanceError` | Not enough credits for tool call | Deposit credits via `deposit` tool |
| 402 | `payment_required` | -- | x402 payment required (no API key, x402 enabled) | Attach `X-PAYMENT` header |
| 402 | `payment_verification_failed` | `X402VerificationError` | x402 payment proof invalid | Check proof format and signature |
| 402 | `payment_replay_detected` | `X402ReplayError` | x402 nonce already used | Generate a new nonce |
| 403 | `insufficient_tier` | `TierInsufficientError` | Agent tier too low for tool | Upgrade tier or use an allowed tool |
| 403 | `forbidden` | -- | Agent tried to create key for another agent | Only admin can create keys for others |
| 404 | `service_not_found` | `ServiceNotFoundError` | Marketplace service not found | Verify service ID |
| 404 | `server_not_found` | `ServerNotFoundError` | Trust server not found | Verify server ID |
| 404 | `intent_not_found` | `IntentNotFoundError` | Payment intent not found | Verify intent ID |
| 404 | `escrow_not_found` | `EscrowNotFoundError` | Escrow not found | Verify escrow ID |
| 404 | `wallet_not_found` | `WalletNotFoundError` | No wallet for this agent | Create wallet via `create_wallet` |
| 404 | `subscription_not_found` | `SubscriptionNotFoundError` | Subscription not found | Verify subscription ID |
| 404 | `agent_not_found` | `AgentNotFoundError` | Agent identity not found | Register via `register_agent` |
| 404 | `dispute_not_found` | `DisputeNotFoundError` | Dispute not found | Verify dispute ID |
| 404 | `not_found` | `ToolNotFoundError` | Generic resource not found | Check resource identifier |
| 409 | `invalid_state` | `InvalidStateError`, `SubscriptionStateError` | Resource in wrong state for operation | Check current state before operating |
| 409 | `duplicate_intent` | `DuplicateIntentError` | Duplicate idempotency key for intent | Use a unique idempotency key |
| 409 | `duplicate_service` | `DuplicateServiceError` | Service with same ID already exists | Use a different service name |
| 409 | `agent_already_exists` | `AgentAlreadyExistsError` | Agent ID already registered | Use the existing agent |
| 409 | `dispute_state_error` | `DisputeStateError` | Dispute in wrong state for operation | Check dispute status |
| 429 | `rate_limit_exceeded` | `RateLimitError`, `RateLimitExceededError` | Hourly or per-tool rate limit exceeded | Wait and retry; check `X-RateLimit-Reset` |
| 429 | `spend_cap_exceeded` | `SpendCapExceededError` | Budget spending cap reached | Increase cap via `set_budget_cap` |
| 500 | `pricing_error` | `NegativeCostError` | Internal pricing calculation error | Contact support |
| 500 | `internal_error` | (any unhandled) | Unexpected server error | Retry; contact support if persistent |
| 501 | `not_implemented` | -- | Tool cataloged but not yet implemented | Check for updates |
| 503 | `service_error` | -- | Rate limit service unavailable | Retry after brief delay |

---

## 6. Rate Limiting

### How Rate Limits Work

Rate limiting uses a **sliding window** algorithm over a 1-hour window:

1. **Global rate limit:** Each agent has a maximum number of requests per hour based on their tier (see [Tier Hierarchy](#tier-hierarchy)).
2. **Burst allowance:** When the global limit is reached, a secondary 1-minute burst window is checked. The burst limit is `(rate_limit_per_hour / 60) + burst_allowance`.
3. **Per-tool rate limit:** Individual tools may define their own `rate_limit_per_hour` in the catalog, checked independently.

### Rate Limit Headers

Every response from `/v1/execute` and `/v1/batch` includes rate limit headers:

| Header | Description | Example |
|--------|-------------|---------|
| `X-RateLimit-Limit` | Maximum requests per hour | `1000` |
| `X-RateLimit-Remaining` | Requests remaining in current window | `847` |
| `X-RateLimit-Reset` | Seconds until window resets | `2341` |

### Rate Limits by Tier

| Tier | Requests/Hour | Burst Allowance | Effective Burst Limit (per minute) |
|------|--------------|-----------------|--------------------------------------|
| free | 100 | 10 | ~12 |
| starter | 1,000 | 25 | ~42 |
| pro | 10,000 | 100 | ~267 |
| enterprise | 100,000 | 1,000 | ~2,667 |

### Batch Requests

A batch request with N tool calls counts as N individual rate limit events. The balance check validates the total cost upfront, but each call is recorded separately in the rate counter.

---

## 7. Retry Strategies

### Exponential Backoff

When receiving a `429 Rate Limit Exceeded` response, use exponential backoff:

```python
import time
import random

def retry_with_backoff(func, max_retries=5):
    for attempt in range(max_retries):
        response = func()
        if response.status_code != 429:
            return response

        # Check X-RateLimit-Reset header
        reset_seconds = int(response.headers.get("X-RateLimit-Reset", 60))

        # Exponential backoff with jitter
        base_delay = min(reset_seconds, 2 ** attempt)
        jitter = random.uniform(0, base_delay * 0.1)
        delay = base_delay + jitter

        time.sleep(delay)

    raise Exception("Max retries exceeded")
```

### Recommended Retry Schedule

| Attempt | Delay | Cumulative Wait |
|---------|-------|-----------------|
| 1 | 1s + jitter | ~1s |
| 2 | 2s + jitter | ~3s |
| 3 | 4s + jitter | ~7s |
| 4 | 8s + jitter | ~15s |
| 5 | 16s + jitter | ~31s |

### Retryable vs Non-Retryable Errors

**Retryable (use backoff):**
- `429` -- Rate limit exceeded
- `503` -- Service temporarily unavailable
- `500` -- Internal errors (may be transient)

**Non-retryable (fix the request):**
- `400` -- Bad request, validation errors
- `401` -- Authentication failure
- `402` -- Insufficient balance (deposit credits first)
- `403` -- Insufficient tier
- `404` -- Resource not found
- `409` -- Conflict/duplicate

### Using X-RateLimit-Reset

When the `X-RateLimit-Reset` header is present, it indicates the number of seconds until the rate limit window resets. Prefer using this value over fixed backoff intervals:

```python
reset_seconds = int(response.headers.get("X-RateLimit-Reset", 60))
time.sleep(reset_seconds)
```

---

## 8. Idempotency

### How Idempotency Keys Work

Payment intents support idempotency keys to prevent duplicate charges. When you provide an `idempotency_key` parameter to `create_intent`, the system guarantees that retrying the same request with the same key will not create a duplicate intent.

### Usage

```bash
curl -X POST http://localhost:8000/v1/execute \
  -H "Authorization: Bearer a2a_free_..." \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "create_intent",
    "params": {
      "payer": "buyer-agent",
      "payee": "seller-agent",
      "amount": 50.0,
      "idempotency_key": "order-2026-03-29-001"
    }
  }'
```

### Correlation-Based Idempotency

Every request that passes through the gateway is assigned a correlation ID (available in the `X-Request-ID` response header). The system uses `{correlation_id}:{tool_name}` as an internal idempotency key for usage recording, preventing duplicate charges on retried requests.

For batch requests, idempotency keys are structured as `{correlation_id}:{batch_index}:{tool_name}`, ensuring each call within a batch is independently idempotent.

### Duplicate Intent Detection

If you attempt to create an intent with an `idempotency_key` that has already been used, the system returns:

```json
{
  "success": false,
  "error": {
    "code": "duplicate_intent",
    "message": "Intent with this idempotency key already exists"
  }
}
```

HTTP status: `409 Conflict`

### Best Practices

1. **Always use idempotency keys** for financial operations (`create_intent`, `create_escrow`, `create_split_intent`).
2. Use deterministic keys derived from your business logic (e.g., `order-{order_id}`, `subscription-{sub_id}-{period}`).
3. Do not reuse idempotency keys for different operations.
4. Store the idempotency key alongside your local transaction record for reconciliation.

---

## Appendix: Credit System

- **Exchange rate:** 100 credits per $1 USD
- **Minimum purchase:** 100 credits ($1.00)
- **Maximum per transaction:** 1,000,000 credits ($10,000)
- **Signup bonus:** 500 credits ($5.00)

### Credit Packages (Stripe)

| Package | Credits | Price | Effective Rate |
|---------|---------|-------|----------------|
| Starter | 1,000 | $10.00 | $0.010/credit |
| Growth | 5,000 | $45.00 | $0.009/credit |
| Scale | 25,000 | $200.00 | $0.008/credit |
| Enterprise | 100,000 | $750.00 | $0.0075/credit |

### Volume Discounts

Discounts are applied based on historical usage (total calls per tool):

| Minimum Calls | Discount |
|--------------|----------|
| 100 | 5% |
| 500 | 10% |
| 1,000 | 15% |

### Auto-Reload

Auto-reload can be configured to automatically purchase credits when the balance drops below a threshold:

- **Default threshold:** 100 credits
- **Default reload amount:** 1,000 credits
- **Enabled by default:** No

### Budget Alerts

Budget alerts trigger at 80% of configured daily/monthly caps (configurable via `set_budget_cap`).
