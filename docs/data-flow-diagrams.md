# Data Flow Diagrams — A2A Commerce Platform

**Version:** 1.0
**Last updated:** 2026-04-04

---

## 1. Agent Registration Flow

```
                    ┌─────────┐
                    │  Agent  │
                    └────┬────┘
                         │ POST /v1/tools/register_agent
                         │ {name, capabilities, ...}
                         ▼
                    ┌──────────┐
                    │Cloudflare│  TLS 1.3 termination
                    │   WAF    │  DDoS protection
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
                    │  nginx   │  Reverse proxy
                    │  :443    │  Rate limiting
                    └────┬─────┘
                         │ http://127.0.0.1:8000
                         ▼
                    ┌──────────────┐
                    │ A2A Gateway   │
                    │ (FastAPI)     │
                    ├──────────────┤
                    │ 1. Validate   │  Pydantic model validation
                    │    request    │  extra="forbid"
                    │              │
                    │ 2. Authenticate│  API key → SHA3-256 hash
                    │    via key    │  lookup in billing.db
                    │              │
                    │ 3. Check tier │  Free/Pro/Enterprise
                    │    & limits   │  rate limit check
                    │              │
                    │ 4. Execute    │  Tool handler logic
                    │    tool       │
                    └──┬───┬───┬───┘
                       │   │   │
              ┌────────┘   │   └────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │identity  │ │marketplace│ │  billing  │
        │  .db     │ │   .db    │ │   .db    │
        └──────────┘ └──────────┘ └──────────┘
        Agent profile  Catalog      API key +
        DID claims     Listings     Usage tracking
```

---

## 2. Authenticated Request Pipeline

```
   Client Request
        │
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │                    MIDDLEWARE CHAIN                       │
  │                                                          │
  │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
  │  │ Correlation  │→│  Structured  │→│   Metrics     │  │
  │  │ ID (X-Req-ID)│  │   Logging    │  │  (Prometheus) │  │
  │  └─────────────┘  └──────────────┘  └───────────────┘  │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Rate Limiter   │  Per-key + public limits
                    │  (in-memory)    │  1000 req/hr public
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Auth: API Key  │  X-Api-Key header
                    │  SHA3-256 hash  │  → lookup in billing.db
                    │  constant-time  │  → resolve tier
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Tool Dispatch  │  TOOL_REGISTRY lookup
                    │  Catalog check  │  Tier → allowed tools
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Tool Handler   │  Business logic
                    │  (product module)│  Database operations
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Response       │  RFC 9457 errors
                    │  Serialization  │  Envelope-free JSON
                    │  + Headers      │  X-Request-ID, X-RateLimit-*
                    └─────────────────┘
```

---

## 3. Payment Lifecycle

```
  Agent A (buyer)                    A2A Gateway                    Agent B (seller)
       │                                │                                │
       │  create_payment_intent         │                                │
       │  {to: B, amount: 10.00,       │                                │
       │   currency: USD}               │                                │
       ├───────────────────────────────►│                                │
       │                                │  1. Validate intent            │
       │                                │  2. Check balance (A)          │
       │                                │  3. Create PENDING intent      │
       │   ◄────────────────────────────┤     in payments.db             │
       │   {intent_id, status: PENDING} │                                │
       │                                │                                │
       │  confirm_payment               │                                │
       │  {intent_id}                   │                                │
       ├───────────────────────────────►│                                │
       │                                │  4. Debit A wallet             │
       │                                │  5. Credit B wallet            │
       │                                │  6. Record transaction         │
       │                                │  7. Emit payment.completed     │
       │                                │     event on EventBus          │
       │   ◄────────────────────────────┤                                │
       │   {status: COMPLETED}          │                                │
       │                                │  8. Webhook delivery ─────────►│
       │                                │     (if registered)            │
       │                                │                                │
       │                                │         REFUND FLOW            │
       │  request_refund                │                                │
       │  {payment_id, reason}          │                                │
       ├───────────────────────────────►│                                │
       │                                │  9. Validate refund window     │
       │                                │ 10. Reverse wallet entries     │
       │                                │ 11. Emit payment.refunded      │
       │   ◄────────────────────────────┤                                │
       │   {status: REFUNDED}           │                                │

  Data stores:
    payments.db  — intents, transactions, refunds
    billing.db   — wallet balances, usage tracking
    event_bus.db — event log for audit trail
```

---

## 4. Data at Rest Topology

```
  /var/lib/a2a/                          Encryption Status
  ├── billing.db ─────────────────────── Wallet balances, API key hashes (SHA3-256)
  │                                      API keys: one-way hashed, never stored raw
  ├── paywall.db ─────────────────────── Rate plans, usage events
  ├── payments.db ────────────────────── Payment intents, transactions
  ├── marketplace.db ─────────────────── Agent catalog, service listings
  ├── trust.db ───────────────────────── Trust scores, reviews, evidence
  ├── identity.db ────────────────────── Agent profiles, DID claims, credentials
  ├── event_bus.db ───────────────────── Cross-product event log (audit trail)
  ├── webhooks.db ────────────────────── Webhook endpoints + delivery log
  ├── messaging.db ───────────────────── Agent-to-agent messages
  └── disputes.db ────────────────────── Payment disputes, evidence

  /var/backups/a2a/                      Backup Policy
  └── <date>/
      └── *.db ───────────────────────── Daily automated backup (cron)
                                         encrypt_backup() for encrypted copies
                                         30-day retention

  Security controls:
  ├── File permissions: 0600 (owner: a2a:a2a)
  ├── Directory: 0700
  ├── systemd: ProtectSystem=strict, ReadWritePaths=/var/lib/a2a
  └── No PII beyond agent_id + API key hash
```

---

## 5. Data in Transit Path

```
  External Client
       │
       │ HTTPS (TLS 1.3)
       │ Cloudflare-managed certificate
       │ Wildcard: *.greenhelix.net
       ▼
  ┌──────────────────────────┐
  │     Cloudflare Edge      │
  │  ┌────────────────────┐  │
  │  │ WAF rules          │  │  Block malicious patterns
  │  │ DDoS mitigation    │  │  L3/L4/L7 protection
  │  │ Bot management     │  │  Challenge suspicious clients
  │  │ TLS termination    │  │  Client ↔ Cloudflare: TLS 1.3
  │  └────────────────────┘  │
  └──────────┬───────────────┘
             │
             │ HTTPS (Full Strict)
             │ Cloudflare ↔ Origin: TLS 1.3
             │ Origin certificate validation
             ▼
  ┌──────────────────────────┐
  │     Origin Server        │
  │  ┌────────────────────┐  │
  │  │ nginx :443         │  │  Reverse proxy
  │  │ UFW: 443 from CF   │  │  Firewall: Cloudflare IPs only
  │  │ only               │  │
  │  └────────┬───────────┘  │
  │           │               │
  │           │ HTTP (localhost only)
  │           │ 127.0.0.1:8000
  │           ▼               │
  │  ┌────────────────────┐  │
  │  │ A2A Gateway        │  │  No network exposure
  │  │ (uvicorn)          │  │  Binds to localhost
  │  └────────────────────┘  │
  └──────────────────────────┘

  Internal services (monitoring):
  ┌──────────────────────────┐
  │     Tailscale Mesh VPN   │
  │                          │
  │  Prometheus :9090 ───────│── Scrape metrics (internal only)
  │  Grafana    :3030 ───────│── Dashboards (internal only)
  │  Loki       :3100 ───────│── Log aggregation (internal only)
  │  Alertmanager :9093 ─────│── Alert routing (internal only)
  │                          │
  │  Access: Tailscale ACL   │
  │  No public exposure      │
  └──────────────────────────┘
```
