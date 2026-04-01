# External API Security & Functional Audit

## Objective

Perform a comprehensive black-box audit of the A2A Commerce Platform API from the perspective of an external agent. This prompt is self-contained — it includes pre-generated API keys, full endpoint coverage, and expected behaviors. Execute every test phase sequentially, record all findings, and produce a structured report at the end.

**Success criteria:** Every endpoint tested, all security controls verified, all edge cases exercised, zero false positives (verify before reporting).

---

## Target Environment

| Property | Value |
|---|---|
| **Base URL** | `https://api.greenhelix.net` |
| **Protocol** | HTTPS (TLS 1.3, behind Cloudflare) |
| **API Version** | v0.7.0 |
| **Auth methods** | `Authorization: Bearer <key>` (preferred) or `X-API-Key: <key>` |
| **Error format** | RFC 9457 Problem Details (`application/problem+json`) |
| **Monetary fields** | Always serialized as 2-decimal strings (e.g., `"500.00"`) |
| **Timestamps** | ISO 8601 UTC (from Unix epoch) |
| **Request body limit** | 1 MB (returns 413 if exceeded) |
| **Request timeout** | 30 seconds (returns 504 if exceeded) |
| **Validation** | Pydantic `extra="forbid"` on all request models — unknown fields → 422 |

---

## Authentication Keys (Pre-Generated)

All keys below are live on sandbox. The `admin` agent has a wallet with 100,000.00 credits.

| Tier | API Key | Agent ID | Rate Limit |
|---|---|---|---|
| **Free** | `a2a_free_fd6f55e3e27cacf45527d574` | `admin` | 100/hr (burst +10) |
| **Starter** | `a2a_starter_7c305eb003f4e8fad383ac47` | `admin` | 1,000/hr (burst +25) |
| **Pro** | `a2a_pro_695ed84d4f10b0167dd15570` | `admin` | 10,000/hr (burst +100) |
| **Admin** | `a2a_pro_307702814d8bdf0471ba5621` | `admin` | Unlimited (admin bypass) |

> **Admin key** has `scopes=["read","write","admin"]`. Use this for admin-only endpoints (audit log, dispute resolution, wallet freeze/unfreeze).

### Secondary Agent (for BOLA Testing)

A second agent exists for cross-agent access tests:

| Agent ID | Has Wallet | Balance |
|---|---|---|
| `audit-agent-2026-04-01` | Yes | 500.00 credits |
| `audit-tester-f17d3f8d` | No (identity only) | N/A |

These agents have **no API keys**. Use the admin key to access their resources (should succeed), then use the free/starter/pro keys (owned by `admin`) to access them (should return 403 — ownership mismatch).

### Key Regeneration (if keys expire or are revoked)

```bash
# Register a new agent + free key
curl -X POST https://api.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "new-agent-ID"}'

# Create additional keys (authenticated)
curl -X POST https://api.greenhelix.net/v1/infra/keys \
  -H "Authorization: Bearer <existing_key>" \
  -H "Content-Type: application/json" \
  -d '{"tier": "starter"}'
```

---

## API Overview

~123 endpoints across 12 domains: health, pricing, registration, billing, payments, disputes, identity, marketplace, messaging, trust, infrastructure, and streaming.

### Tier Hierarchy

```
free < starter < pro < enterprise
```

Higher tiers can access all tools available to lower tiers. Admin is a special scope (not a tier) that bypasses all ownership and tier checks.

### Credit System

- 100 credits = $1 USD
- Signup bonus: 500 credits
- Volume discounts: 5% at 100 calls, 10% at 500, 15% at 1000

---

## Test Phases

### Phase 1: Discovery & Public Endpoints (No Auth)

Test all unauthenticated endpoints. Verify they return correct data without requiring an API key.

| # | Method | Path | Expected | Verify |
|---|---|---|---|---|
| 1.1 | GET | `/v1/health` | 200 — `status: "ok"`, version, db status, tool count | Response includes `databases` map with all DBs "ok" |
| 1.2 | GET | `/v1/pricing` | 200 — paginated tool list | Supports `limit`, `offset`, `cursor` query params |
| 1.3 | GET | `/v1/pricing/summary` | 200 — tools grouped by service | Each service has `tool_count` and `tools` array |
| 1.4 | GET | `/v1/pricing/{tool}` | 200 — single tool pricing | Try `get_balance` (exists) and `nonexistent_tool` (should 404) |
| 1.5 | GET | `/v1/onboarding` | 200 — enriched OpenAPI spec with quickstart | Contains auth instructions and example requests |
| 1.6 | GET | `/v1/openapi.json` | 200 — OpenAPI 3.1.0 spec | Valid JSON schema, includes all endpoints |
| 1.7 | GET | `/v1/signing-key` | 200 — public key for signature verification | Returns a public key string |

**Security checks for Phase 1:**
- All responses include security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`, `Content-Security-Policy: default-src 'none'`
- All responses include `X-Request-ID` header (UUID format)

**Legacy redirects (backward compatibility):**

| # | Method | Legacy Path | Expected |
|---|---|---|---|
| 1.8 | GET | `/health` | 301 → `/v1/health` |
| 1.9 | GET | `/pricing` | 301 → `/v1/pricing` |
| 1.10 | GET | `/pricing/get_balance` | 301 → `/v1/pricing/get_balance` |
| 1.11 | POST | `/execute` | 307 → `/v1/execute` |

---

### Phase 2: Registration & Key Management

Use the **free** key unless noted.

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 2.1 | POST | `/v1/register` | `{"agent_id": "test-reg-<random>"}` | 201 — returns `agent_id`, `api_key`, `tier: "free"`, `balance` |
| 2.2 | POST | `/v1/register` | Same agent_id as 2.1 | 409 — `already-exists` |
| 2.3 | POST | `/v1/register` | `{}` (missing agent_id) | 400 — `Missing required field: agent_id` |
| 2.4 | POST | `/v1/register` | `{"agent_id": "x", "extra": 1}` | 400 — extra fields rejected (manual validation, not Pydantic on this endpoint) |
| 2.5 | POST | `/v1/infra/keys` | `{"tier": "free"}` | 201 — new key created for authenticated agent |
| 2.6 | POST | `/v1/infra/keys` | `{"tier": "starter"}` | 201 — starter key created |
| 2.7 | POST | `/v1/infra/keys` | `{"tier": "pro"}` | 201 — pro key created |
| 2.8 | GET | `/v1/infra/keys` | — | 200 — list of keys for authenticated agent |
| 2.9 | POST | `/v1/infra/keys/rotate` | `{"current_key": "<free_key>"}` | 200 — old key revoked, new key returned |
| 2.10 | POST | `/v1/infra/keys/revoke` | `{"key_hash_prefix": "<prefix>"}` | 200 — key revoked (get prefix from key list) |

> **After Phase 2**: If you rotated/revoked the free key, generate a replacement before continuing.

---

### Phase 3: Billing & Wallet Operations

Use the **free** key (agent: `admin`). All wallet paths use `admin` as `{agent_id}`.

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 3.1 | GET | `/v1/billing/wallets/admin/balance` | — | 200 — `{"balance": "100000.00"}` (or current) |
| 3.2 | GET | `/v1/billing/wallets/admin/balance?currency=EUR` | — | 200 — balance converted to EUR |
| 3.3 | POST | `/v1/billing/wallets/admin/deposit` | `{"amount": "10.00"}` | 200 — deposit confirmed |
| 3.4 | POST | `/v1/billing/wallets/admin/deposit` | Same body + `Idempotency-Key: test-idem-1` | 200 — deposit processed |
| 3.5 | POST | `/v1/billing/wallets/admin/deposit` | Same body + same `Idempotency-Key: test-idem-1` | 200 — **same result** (deduplicated, no double-charge) |
| 3.6 | POST | `/v1/billing/wallets/admin/withdraw` | `{"amount": "5.00"}` | 200 — withdrawal confirmed |
| 3.7 | GET | `/v1/billing/wallets/admin/transactions` | `?limit=5` | 200 — recent transactions, max 5 |
| 3.8 | GET | `/v1/billing/wallets/admin/usage` | — | 200 — usage summary (total_cost, calls, tokens) |
| 3.9 | GET | `/v1/billing/wallets/admin/analytics` | — | 200 — service-level analytics |
| 3.10 | GET | `/v1/billing/wallets/admin/revenue` | `?limit=5` | 200 — revenue report |
| 3.11 | GET | `/v1/billing/wallets/admin/timeseries` | `?interval=hour&limit=5` | 200 — hourly metrics |
| 3.12 | GET | `/v1/billing/wallets/admin/budget` | — | 200 — budget caps and spending |
| 3.13 | PUT | `/v1/billing/wallets/admin/budget` | `{"daily_cap": "1000.00", "monthly_cap": "10000.00", "alert_threshold": "0.8"}` | 200 — budget set |
| 3.14 | GET | `/v1/billing/estimate` | `?tool=get_balance` | 200 — cost estimate |
| 3.15 | GET | `/v1/billing/discounts` | `?agent_id=admin&tool=get_balance&quantity=100` | 200 — volume discount info |
| 3.16 | GET | `/v1/billing/exchange-rates` | `?from=USD&to=EUR` | 200 — exchange rate |
| 3.17 | POST | `/v1/billing/wallets/admin/convert` | `{"from_currency": "USD", "to_currency": "EUR", "amount": "1.00"}` | 200 — balance converted |
| 3.18 | GET | `/v1/billing/leaderboard` | `?metric=spend&limit=5` | 200 — agent leaderboard |

**Admin-only wallet operations (use admin key):**

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 3.19 | POST | `/v1/billing/wallets/admin/freeze` | `{}` | 200 — wallet frozen (use admin key) |
| 3.20 | POST | `/v1/billing/wallets/admin/unfreeze` | `{}` | 200 — wallet unfrozen (use admin key) |

**Negative tests:**

| # | Test | Expected |
|---|---|---|
| 3.21 | GET `/v1/billing/wallets/audit-agent-2026-04-01/balance` with free key | 403 — ownership mismatch |
| 3.22 | POST deposit with `{"amount": "not-a-number"}` | 422 — validation error |
| 3.23 | POST deposit with `{"amount": "-10.00"}` | 400 or 422 — negative amount rejected |

---

### Phase 4: Payment Flows

Use the **free** key for basic operations. Use **pro** key for escrow release and settlements.

#### 4A: Payment Intents

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 4.1 | POST | `/v1/payments/intents` | `{"payer": "admin", "payee": "audit-agent-2026-04-01", "amount": "10.00", "currency": "USD"}` | 201 — intent created, returns `intent_id` |
| 4.2 | GET | `/v1/payments/intents` | `?limit=5` | 200 — list of intents |
| 4.3 | GET | `/v1/payments/intents/{intent_id}` | — | 200 — intent details, status "pending" |
| 4.4 | POST | `/v1/payments/intents/{intent_id}/capture` | `{}` | 200 — intent captured |
| 4.5 | POST | `/v1/payments/intents/{intent_id}/refund` | `{}` | 200 — captured intent refunded |
| 4.6 | POST | `/v1/payments/intents/split` | `{"payer": "admin", "payees": [{"agent_id": "audit-agent-2026-04-01", "amount": "5.00"}], "currency": "USD"}` | 201 — split intent created |
| 4.7 | POST | `/v1/payments/intents/{id}/partial` | `{"amount": "3.00"}` | 200 — partial capture |

#### 4B: Escrow

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 4.8 | POST | `/v1/payments/escrow` | `{"payer": "admin", "payee": "audit-agent-2026-04-01", "amount": "20.00", "currency": "USD"}` | 201 — escrow created |
| 4.9 | GET | `/v1/payments/escrow` | `?limit=5` | 200 — list escrows |
| 4.10 | GET | `/v1/payments/escrow/{escrow_id}` | — | 200 — escrow details |
| 4.11 | POST | `/v1/payments/escrow/{escrow_id}/release` | `{}` (use **pro** key) | 200 — funds released |
| 4.12 | POST (new escrow) | `/v1/payments/escrow` | Create another escrow | 201 |
| 4.13 | POST | `/v1/payments/escrow/{escrow_id}/cancel` | `{}` | 200 — escrow cancelled, payer refunded |

**Performance escrow (pro key):**

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 4.14 | POST | `/v1/payments/escrow/performance` | `{"payer": "admin", "payee": "audit-agent-2026-04-01", "amount": "15.00", "currency": "USD", "metric_name": "uptime", "threshold": 99.0}` | 201 — performance escrow created |
| 4.15 | POST | `/v1/payments/escrow/performance/{id}/check` | `{}` | 200 — performance metric check result |

#### 4C: Subscriptions (starter+ key)

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 4.16 | POST | `/v1/payments/subscriptions` | `{"subscriber": "admin", "provider": "audit-agent-2026-04-01", "amount": "50.00", "currency": "USD", "interval": "monthly"}` | 201 — subscription created |
| 4.17 | GET | `/v1/payments/subscriptions` | `?limit=5` | 200 — list subscriptions |
| 4.18 | GET | `/v1/payments/subscriptions/{sub_id}` | — | 200 — subscription details |
| 4.19 | POST | `/v1/payments/subscriptions/{sub_id}/cancel` | `{}` | 200 — subscription cancelled |
| 4.20 | POST | `/v1/payments/subscriptions/{sub_id}/reactivate` | `{}` | 200 — subscription reactivated |
| 4.21 | POST | `/v1/payments/subscriptions/process-due` | `{}` (use **pro** key) | 200 — batch process due subscriptions |

#### 4D: Payment History & Settlements

| # | Method | Path | Expected |
|---|---|---|---|
| 4.22 | GET | `/v1/payments/history?agent_id=admin&limit=10` | 200 — payment history |
| 4.23 | POST | `/v1/payments/settlements/{id}/refund` (pro key) | 200 — settlement refunded (use a settlement ID from history) |

---

### Phase 5: Disputes

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 5.1 | POST | `/v1/disputes` (pro key) | `{"escrow_id": "<from Phase 4>", "opener": "admin", "reason": "Service not delivered"}` | 201 — dispute opened |
| 5.2 | GET | `/v1/disputes?limit=5` | — | 200 — list disputes |
| 5.3 | GET | `/v1/disputes/{dispute_id}` | — | 200 — dispute details |
| 5.4 | POST | `/v1/disputes/{dispute_id}/respond` | `{"responder": "audit-agent-2026-04-01", "response": "Service was delivered on time"}` | This may fail with 403 unless using a key for audit-agent-2026-04-01; document behavior |
| 5.5 | POST | `/v1/disputes/{dispute_id}/resolve` (admin key) | `{"resolution": "refund", "notes": "Audit test"}` | 200 — dispute resolved by admin |

---

### Phase 6: Identity & Reputation

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 6.1 | POST | `/v1/identity/agents` | `{"agent_id": "admin"}` | 201 or 409 — register agent identity |
| 6.2 | GET | `/v1/identity/agents/admin` | — | 200 — agent identity (public lookup, no ownership check) |
| 6.3 | POST | `/v1/identity/agents/admin/verify` | `{"signature": "test", "message": "hello"}` | 200 — verification result |
| 6.4 | POST | `/v1/identity/orgs` | `{"org_id": "audit-org", "name": "Audit Org"}` | 201 — org created |
| 6.5 | GET | `/v1/identity/orgs/audit-org` | — | 200 — org details |
| 6.6 | POST | `/v1/identity/orgs/audit-org/members` | `{"agent_id": "admin"}` | 200 — member added |
| 6.7 | DELETE | `/v1/identity/orgs/audit-org/members/admin` | — | 200 — member removed |
| 6.8 | POST | `/v1/identity/metrics/ingest` | `{"agent_id": "admin", "metrics": {"uptime": 99.5}, "data_source": "external"}` | 200 — metrics ingested |
| 6.9 | POST | `/v1/identity/metrics/submit` (pro key) | `{"agent_id": "admin", "metrics": {"quality": 4.5}}` | 200 — self-reported metrics |
| 6.10 | GET | `/v1/identity/metrics/query?agent_id=admin&metric_names=uptime` | — | 200 — metric values |
| 6.11 | GET | `/v1/identity/metrics/deltas?agent_id=admin` | — | 200 — metric changes |
| 6.12 | GET | `/v1/identity/metrics/averages?agent_id=admin` | — | 200 — metric averages |
| 6.13 | GET | `/v1/identity/agents/admin/reputation` | — | 200 — reputation score |
| 6.14 | GET | `/v1/identity/agents/admin/claims` | — | 200 — verified claims |
| 6.15 | POST | `/v1/identity/claims/build-chain` (pro key) | `{"root_claims": [{"claim": "verified-identity", "agent_id": "admin"}]}` | 200 — claim chain built |
| 6.16 | GET | `/v1/identity/claims/chains?agent_id=admin` (pro key) | — | 200 — claim chains |
| 6.17 | GET | `/v1/identity/agents?metric_name=uptime&min_value=50&limit=5` (pro key) | — | 200 — search agents by metrics |

---

### Phase 7: Marketplace

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 7.1 | POST | `/v1/marketplace/services` (pro key) | `{"provider_id": "admin", "name": "Audit Service", "description": "Test service", "category": "testing", "tools": ["get_balance"], "tags": ["audit"], "endpoint": "https://example.com/svc", "pricing": {"per_call": "1.00"}}` | 201 — service registered |
| 7.2 | GET | `/v1/marketplace/services?limit=5` | — | 200 — list services |
| 7.3 | GET | `/v1/marketplace/services/{service_id}` | — | 200 — service details |
| 7.4 | PUT | `/v1/marketplace/services/{service_id}` | `{"name": "Updated Audit Service"}` | 200 — service updated |
| 7.5 | POST | `/v1/marketplace/services/{service_id}/ratings` | `{"rating": 5, "review": "Excellent"}` | 200 — rating submitted |
| 7.6 | GET | `/v1/marketplace/services/{service_id}/ratings` | — | 200 — list ratings |
| 7.7 | GET | `/v1/marketplace/match?query=testing&limit=3` | — | 200 — best-match results |
| 7.8 | GET | `/v1/marketplace/agents?query=admin&limit=5` | — | 200 — agent search |
| 7.9 | GET | `/v1/marketplace/strategies?limit=5` | — | 200 — list strategies |
| 7.10 | POST | `/v1/marketplace/services/{service_id}/deactivate` | `{}` | 200 — service deactivated |

---

### Phase 8: Trust & Infrastructure

#### 8A: Trust — Server Management

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 8.1 | POST | `/v1/trust/servers` | `{"name": "audit-server", "url": "https://example.com", "transport_type": "http"}` | 201 — server registered |
| 8.2 | GET | `/v1/trust/servers?limit=5` | — | 200 — list servers |
| 8.3 | GET | `/v1/trust/servers/{server_id}/score?window=24h` | — | 200 — trust score |
| 8.4 | GET | `/v1/trust/servers/{server_id}/sla?claimed_uptime=99.9` | — | 200 — SLA compliance check |
| 8.5 | PUT | `/v1/trust/servers/{server_id}` (pro key) | `{"name": "updated-server"}` | 200 — server updated |
| 8.6 | DELETE | `/v1/trust/servers/{server_id}` (pro key) | — | 200 — server deleted |

#### 8B: Infrastructure — Webhooks

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 8.7 | POST | `/v1/infra/webhooks` (pro key) | `{"url": "https://example.com/hook", "event_types": ["payment.completed"], "secret": "wh-secret-123"}` | 201 — webhook registered |
| 8.8 | GET | `/v1/infra/webhooks` (pro key) | — | 200 — list webhooks |
| 8.9 | POST | `/v1/infra/webhooks/{webhook_id}/test` | `{}` | 200 — test delivery result |
| 8.10 | GET | `/v1/infra/webhooks/{webhook_id}/deliveries` (pro key) | `?limit=5` | 200 — delivery history |
| 8.11 | DELETE | `/v1/infra/webhooks/{webhook_id}` (pro key) | — | 200 — webhook deleted |

#### 8C: Infrastructure — Events

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 8.12 | POST | `/v1/infra/events/schemas` | `{"event_type": "audit.test", "schema": {"type": "object", "properties": {"msg": {"type": "string"}}}}` | 201 — schema registered |
| 8.13 | GET | `/v1/infra/events/schemas/audit.test` | — | 200 — schema definition |
| 8.14 | POST | `/v1/infra/events` | `{"event_type": "audit.test", "source": "auditor", "payload": {"msg": "hello"}}` | 201 — event published |
| 8.15 | GET | `/v1/infra/events?event_type=audit.test&limit=5` | — | 200 — list events |

#### 8D: Infrastructure — Audit Log (Admin Only)

| # | Method | Path | Expected |
|---|---|---|---|
| 8.16 | GET | `/v1/infra/audit-log?limit=10` (admin key) | 200 — global audit entries |
| 8.17 | GET | `/v1/infra/audit-log?limit=10` (free key) | 403 — insufficient tier/scopes |

#### 8E: Infrastructure — Database Operations (Pro Key)

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 8.18 | GET | `/v1/infra/databases/backups` | — | 200 — list backups |
| 8.19 | POST | `/v1/infra/databases/billing/backup` | `{"encrypt": false}` | 200 — backup created |
| 8.20 | GET | `/v1/infra/databases/billing/integrity` | — | 200 — integrity check result |
| 8.21 | POST | `/v1/infra/databases/billing/restore` | `{"backup_path": "<from 8.19>"}` | 200 — restore executed |

---

### Phase 9: Messaging

| # | Method | Path | Body / Params | Expected |
|---|---|---|---|---|
| 9.1 | POST | `/v1/messaging/messages` | `{"sender": "admin", "recipient": "audit-agent-2026-04-01", "message_type": "text", "subject": "Audit Test", "body": "Hello from audit"}` | 201 — message sent |
| 9.2 | GET | `/v1/messaging/messages?agent_id=admin&limit=5` | — | 200 — list messages |
| 9.3 | POST | `/v1/messaging/negotiations` | `{"initiator": "admin", "responder": "audit-agent-2026-04-01", "amount": "100.00", "service_id": "test-svc", "expires_hours": 24}` | 201 — negotiation created |

---

### Phase 10: Streaming & Real-time

#### 10A: Server-Sent Events

| # | Method | Path | Expected |
|---|---|---|---|
| 10.1 | GET | `/v1/events/stream` with `Authorization: Bearer <free_key>` | 200 — SSE stream with heartbeat events |

```bash
# Test with curl (auto-closes after a few heartbeats)
curl -N -H "Authorization: Bearer a2a_free_fd6f55e3e27cacf45527d574" \
  https://api.greenhelix.net/v1/events/stream
```

#### 10B: WebSocket

| # | Method | Path | Expected |
|---|---|---|---|
| 10.2 | WS | `/v1/ws` | WebSocket connection; authenticate via header, query param, or in-band `{"type": "auth", "api_key": "..."}` message |

```bash
# Test with websocat or similar
websocat "wss://api.greenhelix.net/v1/ws" \
  -H "Authorization: Bearer a2a_free_fd6f55e3e27cacf45527d574"
```

---

### Phase 11: Tool Execution (Legacy)

Test the generic tool execution endpoint with connector tools that haven't been migrated to REST.

| # | Method | Path | Body | Expected |
|---|---|---|---|---|
| 11.1 | POST | `/v1/execute` | `{"tool": "get_balance", "params": {"agent_id": "admin"}}` | 410 — tool moved to REST endpoint |
| 11.2 | POST | `/v1/batch` | `{"calls": [{"tool": "get_balance", "params": {"agent_id": "admin"}}]}` | 410 or mixed results |
| 11.3 | POST | `/v1/execute` | `{"tool": "stripe_list_customers", "params": {}}` | 200 or 503 depending on Stripe config |

---

### Phase 12: Security & Edge Cases

This is the most critical phase. Test every security control systematically.

#### 12A: Authentication

| # | Test | Method | Expected |
|---|---|---|---|
| 12.1 | No auth header | GET `/v1/billing/wallets/admin/balance` | 401 — `missing-key` |
| 12.2 | Invalid key | Same + `Authorization: Bearer invalid_key_here` | 401 — invalid key |
| 12.3 | Malformed header | Same + `Authorization: NotBearer xxx` | 401 |
| 12.4 | X-API-Key header | Same + `X-API-Key: <free_key>` | 200 — alternative auth works |
| 12.5 | Empty Bearer | Same + `Authorization: Bearer ` | 401 |

#### 12B: BOLA (Broken Object-Level Authorization)

| # | Test | Expected |
|---|---|---|
| 12.6 | Free key → GET `/v1/billing/wallets/audit-agent-2026-04-01/balance` | 403 — `agent_id` mismatch |
| 12.7 | Free key → POST `/v1/billing/wallets/audit-agent-2026-04-01/deposit` with `{"amount": "1.00"}` | 403 |
| 12.8 | Free key → POST `/v1/payments/intents` with `{"payer": "audit-agent-2026-04-01", ...}` | 403 — payer mismatch |
| 12.9 | Admin key → GET `/v1/billing/wallets/audit-agent-2026-04-01/balance` | 200 — admin bypasses ownership |

**Public lookups (should NOT enforce ownership):**

| # | Test | Expected |
|---|---|---|
| 12.10 | Free key → GET `/v1/identity/agents/audit-agent-2026-04-01` | 200 — public lookup OK |
| 12.11 | Free key → GET `/v1/identity/agents/audit-agent-2026-04-01/reputation` | 200 — public lookup OK |
| 12.12 | Free key → GET `/v1/marketplace/services/{any_id}` | 200 — public lookup OK |

#### 12C: Tier Enforcement

| # | Test | Expected |
|---|---|---|
| 12.13 | Free key → POST `/v1/infra/webhooks` | 403 — requires pro |
| 12.14 | Free key → POST `/v1/payments/subscriptions` | 403 — requires starter |
| 12.15 | Starter key → POST `/v1/payments/escrow/performance` | 403 — requires pro |
| 12.16 | Pro key → POST `/v1/infra/webhooks` | 201 — pro meets requirement |
| 12.17 | Free key → GET `/v1/infra/audit-log` | 403 — admin-only |
| 12.18 | Pro key → GET `/v1/infra/audit-log` | 403 — requires admin scope, not just pro tier |

#### 12D: Rate Limiting

| # | Test | Expected |
|---|---|---|
| 12.19 | Send 5 rapid requests with free key | All 200; headers show `X-RateLimit-Limit: 100`, `X-RateLimit-Remaining` decreasing |
| 12.20 | Verify rate limit headers present | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` on every authenticated response |

> Note: Actually triggering 429 requires 100+ requests in an hour window with the free key. If feasible, burst 100+ requests quickly. Otherwise, verify the headers are present and correctly decrementing.

#### 12E: Input Validation

| # | Test | Expected |
|---|---|---|
| 12.21 | POST `/v1/billing/wallets/admin/deposit` with `{"amount": "10.00", "extra_field": true}` | 422 — `extra inputs are not permitted` |
| 12.22 | POST `/v1/payments/intents` with `{"payer": 12345}` (wrong type) | 422 — type validation error |
| 12.23 | POST with invalid JSON body `{invalid` | 400 or 422 — parse error |
| 12.24 | POST with empty body | 422 — missing required fields |
| 12.25 | POST with body > 1MB (send `{"data": "A" * 1048577}`) | 413 — payload too large |

#### 12F: RFC 9457 Error Format

Verify ALL error responses conform to RFC 9457 Problem Details:

```json
{
  "type": "https://api.greenhelix.net/errors/<error-type>",
  "title": "<HTTP Status Text>",
  "status": <HTTP Status Code>,
  "detail": "<Human-readable description>",
  "instance": "<Request Path>"
}
```

| # | Check | Errors to verify |
|---|---|---|
| 12.26 | Content-Type header | `application/problem+json` on all 4xx/5xx responses |
| 12.27 | Required fields | Every error has `type`, `title`, `status`, `detail`, `instance` |
| 12.28 | Type URL format | Starts with `https://api.greenhelix.net/errors/` |
| 12.29 | Status code consistency | `status` field matches HTTP status code |

#### 12G: Security Headers

Verify on EVERY response (both success and error):

| Header | Expected Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` |
| `Content-Security-Policy` | `default-src 'none'` |
| `X-Request-ID` | Present (UUID format) |

#### 12H: CORS

| # | Test | Expected |
|---|---|---|
| 12.30 | OPTIONS preflight to `/v1/health` with `Origin: https://evil.com` | No `Access-Control-Allow-Origin` header (CORS disabled unless configured) |

#### 12I: Monetary Precision

| # | Check | Expected |
|---|---|---|
| 12.31 | All balance responses | String format with 2 decimal places (e.g., `"500.00"`, never `500` or `500.0`) |
| 12.32 | All amount fields in payment responses | Same 2-decimal string format |
| 12.33 | No floating-point artifacts | Never `"499.99999999"` or similar |

#### 12J: Idempotency

| # | Test | Expected |
|---|---|---|
| 12.34 | POST deposit with `Idempotency-Key: unique-1` | 200 — processed |
| 12.35 | Repeat exact same request with same `Idempotency-Key: unique-1` | 200 — same response, balance not double-charged |
| 12.36 | Same key but different body | Behavior documented (should reject or return cached response) |

---

## Execution Instructions

1. **Use `curl`, `httpie`, or equivalent HTTP client** for all requests
2. **Capture full response** including status code, headers, and body for every test
3. **Use the correct key tier** as specified in each test (free/starter/pro/admin)
4. **Record IDs** returned by creation endpoints (intent_id, escrow_id, sub_id, etc.) for use in subsequent tests
5. **Run phases sequentially** — later phases depend on resources created in earlier ones
6. **Mark each test** as PASS, FAIL, or SKIP with explanation
7. **For failures**: include the full request and response for debugging

---

## Reporting Template

After completing all phases, produce a report in this format:

```markdown
# External API Audit Report — [DATE]

## Summary
- **Total tests:** X
- **Passed:** X
- **Failed:** X
- **Skipped:** X

## Critical Findings (Security)
1. [Finding title]
   - **Severity:** Critical/High/Medium/Low
   - **Endpoint:** METHOD /path
   - **Description:** What happened
   - **Expected:** What should have happened
   - **Evidence:** Request + response

## Functional Issues
1. [Issue title]
   - **Endpoint:** METHOD /path
   - **Description:** What happened
   - **Expected:** What should have happened

## Phase Results

### Phase 1: Discovery
| # | Test | Status | Notes |
|---|---|---|---|
| 1.1 | GET /v1/health | PASS | 200 OK, all DBs healthy |
...

### Phase 2: Registration
...

[Continue for all phases]

## Recommendations
1. ...
2. ...
```

---

## Notes

- The sandbox database is shared — other agents may exist. Do not delete or modify resources you didn't create.
- Cloudflare sits in front of the API. You may observe bimodal latency (~200ms fast / ~5s DNS penalty on first request).
- The `admin` agent is a privileged test account. In production, admin keys would not be distributed.
- If any key stops working (401), use `/v1/infra/keys` with a working key to generate a replacement.
- The `/v1/execute` endpoint returns 410 for tools that have been migrated to dedicated REST routes. This is expected behavior.
