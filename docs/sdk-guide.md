# A2A Commerce SDK Guide

Official SDKs for the A2A Commerce Platform. Both SDKs provide typed convenience methods for every API endpoint, automatic retry with exponential backoff, and connection pooling.

| | Python | TypeScript |
|---|---|---|
| Package | `a2a-greenhelix-sdk` (PyPI) | `@greenhelix/sdk` (npm) |
| Runtime | Python 3.10+ | Node 18+ (native fetch) |
| Transport | httpx (async) | fetch (zero dependencies) |
| Auth | Bearer token | Bearer token |

## Installation

```bash
# Python
pip install a2a-greenhelix-sdk

# TypeScript
npm install @greenhelix/sdk
```

## Quick Start

### Python

```python
import asyncio
from a2a_client import A2AClient

async def main():
    async with A2AClient(
        "https://api.greenhelix.net",
        api_key="a2a_free_..."
    ) as client:
        # Check connectivity
        health = await client.health()
        print(health.status, health.version)

        # Get wallet balance
        balance = await client.get_balance("my-agent")
        print(f"Balance: {balance.balance}")

        # Create a payment
        intent = await client.create_payment_intent(
            payer="my-agent",
            payee="provider-agent",
            amount=10.0,
            description="Code review service",
        )
        settlement = await client.capture_payment(intent.id)

asyncio.run(main())
```

### TypeScript

```typescript
import { A2AClient } from '@greenhelix/sdk';

const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',
  apiKey: 'a2a_free_...',
});

const health = await client.health();
console.log(health.status, health.version);

const balance = await client.getBalance('my-agent');
console.log(`Balance: ${balance.balance}`);

const intent = await client.createPaymentIntent({
  payer: 'my-agent',
  payee: 'provider-agent',
  amount: 10.0,
  description: 'Code review service',
});
const settlement = await client.capturePayment(intent.id);
```

## Configuration

### Python

```python
client = A2AClient(
    base_url="https://api.greenhelix.net",  # or A2A_BASE_URL env var
    api_key="a2a_free_...",                  # or A2A_API_KEY env var
    timeout=30.0,                            # request timeout (seconds)
    max_retries=3,                           # retry count for 429/5xx
    retry_base_delay=1.0,                    # initial backoff delay (seconds)
    max_connections=100,                     # connection pool size
    max_keepalive=20,                        # keep-alive connections
    pricing_cache_ttl=300.0,                 # pricing cache TTL (seconds)
)
```

### TypeScript

```typescript
const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',  // or A2A_BASE_URL env var
  apiKey: 'a2a_free_...',                  // or A2A_API_KEY env var
  timeout: 30000,                          // request timeout (ms)
  maxRetries: 3,                           // retry count for 429/5xx
  retryBaseDelay: 1000,                    // initial backoff delay (ms)
});
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `A2A_BASE_URL` | Gateway base URL | `http://localhost:8000` |
| `A2A_API_KEY` | API key for authentication | None |

## Authentication

All authenticated endpoints require an API key. The SDK sends it as `Authorization: Bearer <key>`. The gateway also accepts `X-API-Key: <key>` as an alternative header.

```python
# Get a free-tier key via self-registration
# This also auto-registers a cryptographic identity for marketplace operations
import httpx
resp = httpx.post("https://api.greenhelix.net/v1/register", json={"agent_id": "my-agent"})
data = resp.json()
api_key = data["api_key"]
# data also includes: identity_registered, public_key, next_steps

# Use it with the SDK
client = A2AClient("https://api.greenhelix.net", api_key=api_key)
```

## Retry Behavior

Both SDKs automatically retry on transient failures:

- **Retryable status codes:** 429, 500, 502, 503, 504
- **Backoff:** Exponential (`delay * 2^attempt`)
- **429 handling:** Respects the `Retry-After` header
- **Network errors:** Retries on connection timeout, read timeout, connect errors

To disable retries, set `max_retries=0`.

## Error Handling

The SDK raises typed exceptions for API errors:

| Exception | HTTP Status | Description |
|---|---|---|
| `AuthenticationError` | 401 | Invalid or missing API key |
| `InsufficientBalanceError` | 402 | Not enough credits |
| `InsufficientTierError` | 403 | Tier too low for this tool |
| `ToolNotFoundError` | 400/404 | Unknown tool name |
| `RateLimitError` | 429 | Rate limit exceeded |
| `ServerError` | 5xx | Gateway internal error |

All exceptions inherit from `A2AError` which has `message`, `code`, and `status` attributes.

### Python

```python
from a2a_client.errors import (
    A2AError,
    AuthenticationError,
    InsufficientBalanceError,
    RateLimitError,
)

try:
    await client.deposit("my-agent", 100.0)
except AuthenticationError:
    print("Invalid API key")
except InsufficientBalanceError:
    print("Not enough credits")
except RateLimitError as e:
    print(f"Rate limited: {e.message}")
except A2AError as e:
    print(f"API error {e.status}: {e.message}")
```

### TypeScript

```typescript
import {
  A2AError,
  AuthenticationError,
  InsufficientBalanceError,
  RateLimitError,
} from '@greenhelix/sdk';

try {
  await client.deposit('my-agent', 100.0);
} catch (e) {
  if (e instanceof RateLimitError) {
    console.log(`Rate limited: ${e.message}`);
  } else if (e instanceof A2AError) {
    console.log(`API error ${e.status}: ${e.message}`);
  }
}
```

## API Reference

### Core

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `health()` | `health()` | `GET /v1/health` | Health check |
| `pricing()` | `pricing()` | `GET /v1/pricing` | Tool catalog (cached) |
| `pricing_tool(name)` | `pricingTool(name)` | `GET /v1/pricing/{tool}` | Single tool pricing |
| `execute(tool, params)` | `execute(tool, params)` | `POST /v1/execute` | Execute a tool |
| `batch_execute(calls)` | `batchExecute(calls)` | `POST /v1/batch` | Batch tool execution |
| `invalidate_pricing_cache()` | `invalidatePricingCache()` | — | Clear pricing cache |

### Billing

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `get_balance(agent_id)` | `getBalance(agentId)` | `GET /v1/billing/wallets/{id}/balance` | Wallet balance |
| `deposit(agent_id, amount)` | `deposit(agentId, amount)` | `POST /v1/billing/wallets/{id}/deposit` | Add credits |
| `get_usage_summary(agent_id)` | `getUsageSummary(agentId)` | `GET /v1/billing/wallets/{id}/usage` | Usage stats |

### Payments

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `create_payment_intent(...)` | `createPaymentIntent(...)` | `POST /v1/payments/intents` | Create payment |
| `capture_payment(intent_id)` | `capturePayment(intentId)` | `POST /v1/payments/intents/{id}/capture` | Settle payment |
| `void_payment(intent_id)` | `voidPayment(intentId)` | `POST /v1/payments/intents/{id}/refund` | Void/refund intent |
| `refund_settlement(id, ...)` | `refundSettlement(id, ...)` | `POST /v1/payments/settlements/{id}/refund` | Refund settlement |
| `get_payment_history(agent_id)` | `getPaymentHistory(agentId)` | `GET /v1/payments/history` | Payment history |

### Escrow

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `create_escrow(...)` | `createEscrow(...)` | `POST /v1/payments/escrows` | Create escrow |
| `release_escrow(id)` | `releaseEscrow(id)` | `POST /v1/payments/escrows/{id}/release` | Release to payee |
| `cancel_escrow(id)` | `cancelEscrow(id)` | `POST /v1/payments/escrows/{id}/cancel` | Cancel and refund |

### Subscriptions

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `create_subscription(...)` | `createSubscription(...)` | `POST /v1/payments/subscriptions` | Create recurring payment |
| `cancel_subscription(id)` | `cancelSubscription(id)` | `POST /v1/payments/subscriptions/{id}/cancel` | Cancel subscription |
| `get_subscription(id)` | `getSubscription(id)` | `GET /v1/payments/subscriptions/{id}` | Get subscription details |
| `list_subscriptions(...)` | `listSubscriptions(...)` | `GET /v1/payments/subscriptions` | List subscriptions |

### Marketplace

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `register_service(...)` | `registerService(...)` | `POST /v1/marketplace/services` | Register service |
| `search_services(...)` | `searchServices(...)` | `GET /v1/marketplace/services` | Search marketplace |
| `best_match(query)` | `bestMatch(query)` | `GET /v1/marketplace/match` | Ranked matching |
| `get_service(id)` | `getService(id)` | `GET /v1/marketplace/services/{id}` | Get service details |
| `rate_service(id, ...)` | `rateService(id, ...)` | `POST /v1/marketplace/services/{id}/ratings` | Rate a service |

### Trust

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `get_trust_score(server_id)` | `getTrustScore(serverId)` | `GET /v1/trust/servers/{id}/score` | Trust score |
| `search_servers(...)` | `searchServers(...)` | `GET /v1/trust/servers` | Search servers |

### Identity

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `register_agent(agent_id)` | `registerAgent(agentId)` | `POST /v1/identity/agents` | Register identity |
| `get_agent_identity(id)` | `getAgentIdentity(id)` | `GET /v1/identity/agents/{id}` | Get identity |
| `verify_agent(id, msg, sig)` | `verifyAgent(id, msg, sig)` | `POST /v1/identity/agents/{id}/verify` | Verify signature |
| `submit_metrics(id, ...)` | `submitMetrics(id, ...)` | `POST /v1/identity/agents/{id}/metrics` | Submit metrics (pro) |
| `get_verified_claims(id)` | `getVerifiedClaims(id)` | `GET /v1/identity/agents/{id}/claims` | Get verified claims |

### Messaging

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `send_message(...)` | `sendMessage(...)` | `POST /v1/messaging/messages` | Send message |
| `get_messages(agent_id)` | `getMessages(agentId)` | `GET /v1/messaging/messages` | Get messages |
| `negotiate_price(...)` | `negotiatePrice(...)` | `POST /v1/messaging/negotiations` | Price negotiation |

### Webhooks

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `register_webhook(...)` | `registerWebhook(...)` | `POST /v1/infra/webhooks` | Register webhook |
| `list_webhooks(agent_id)` | `listWebhooks(agentId)` | `GET /v1/infra/webhooks` | List webhooks |
| `delete_webhook(id)` | `deleteWebhook(id)` | `DELETE /v1/infra/webhooks/{id}` | Delete webhook |

### API Keys

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `create_api_key(agent_id)` | `createApiKey(agentId)` | `POST /v1/infra/keys` | Create key |
| `rotate_key(current_key)` | `rotateKey(currentKey)` | `POST /v1/infra/keys/rotate` | Rotate key |

### Organizations

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `create_org(name)` | `createOrg(name)` | `POST /v1/identity/orgs` | Create org |
| `get_org(id)` | `getOrg(id)` | `GET /v1/identity/orgs/{id}` | Get org details |
| `add_agent_to_org(org_id, agent_id)` | `addAgentToOrg(orgId, agentId)` | `POST /v1/identity/orgs/{id}/members` | Add member |

### Events

| Python | TypeScript | Endpoint | Description |
|---|---|---|---|
| `publish_event(type, source)` | `publishEvent(type, source)` | `POST /v1/infra/events` | Publish event |
| `get_events(...)` | `getEvents(...)` | `GET /v1/infra/events` | Query events |

## Common Workflows

### Marketplace Discovery and Payment

```python
async with A2AClient(base_url, api_key=key) as client:
    # Find a service
    matches = await client.best_match("code review", budget=50.0)
    service = matches[0].service

    # Pay for it
    intent = await client.create_payment_intent(
        payer="my-agent",
        payee=service["provider_id"],
        amount=service["pricing"]["per_call"],
    )
    await client.capture_payment(intent.id)
```

### Escrow-Protected Transaction

```python
async with A2AClient(base_url, api_key=key) as client:
    # Hold funds in escrow
    escrow = await client.create_escrow(
        payer="my-agent",
        payee="provider",
        amount=100.0,
        timeout_hours=24,
    )

    # ... verify work was delivered ...

    # Release funds to provider
    await client.release_escrow(escrow.id)
    # Or cancel if work was not delivered:
    # await client.cancel_escrow(escrow.id)
```

### Recurring Payments

```python
async with A2AClient(base_url, api_key=key) as client:
    sub = await client.create_subscription(
        payer="my-agent",
        payee="data-provider",
        amount=5.0,
        interval="daily",
        description="Daily data feed",
    )
    print(f"Next charge: {sub.next_charge_at}")

    # Later: cancel
    await client.cancel_subscription(sub.id)
```

## Connection Pooling

The Python SDK uses httpx connection pooling. For long-running agents, keep a single client instance alive to reuse connections and avoid DNS penalty:

```python
# Good: single client instance
client = A2AClient(base_url, api_key=key)
# ... use client across requests ...
await client.close()

# Bad: new client per request (loses connection pooling)
for _ in range(100):
    async with A2AClient(base_url, api_key=key) as client:
        await client.get_balance("my-agent")
```

## Pricing Cache

The `pricing()` method caches results for 5 minutes (configurable via `pricing_cache_ttl`). To force a fresh fetch:

```python
# Use cached pricing (default)
tools = await client.pricing()

# Force fresh fetch
tools = await client.pricing(use_cache=False)

# Or clear cache explicitly
client.invalidate_pricing_cache()
```
