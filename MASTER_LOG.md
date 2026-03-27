# A2A Commerce Platform — Master Log

This is the running log of all conversations, decisions, and next steps for the A2A Commerce Platform project.

---

## Session 1 — 2026-03-27: Platform Build-Out (12 Improvements)

### Prompt

> Implement the following plan: [12-item implementation plan]

The plan covered 12 improvements organized by priority:

| # | Item | Priority |
|---|------|----------|
| 1 | API Versioning — `/v1/` prefix | High |
| 2 | Webhook Delivery System | High |
| 3 | Subscription Scheduler Gateway Exposure | High |
| 4 | Authentication Hardening — SHA-3 Key Hashing | High |
| 5 | Rate Limiting Improvements (sliding window, burst, per-tool) | Medium |
| 6 | Marketplace Service Health Monitoring | Medium |
| 7 | OpenAPI / JSON Schema Generation | Medium |
| 8 | Observability — Structured Logging, Tracing, Metrics | Medium |
| 9 | CRYSTALS-Dilithium Signatures | Lower |
| 10 | Multi-Tenancy (`org_id`) | Lower |
| 11 | Horizontal Scaling Prep — PostgreSQL DSN parsing | Lower |
| 12 | SDK Improvements — Retry, Pooling, Caching, Types | Lower |

### Response

All 12 items implemented. **750 tests passing** across 8 modules.

**New files created:**
- `gateway/src/webhooks.py` — WebhookManager with HMAC-SHA3 signatures, retry, dead letter
- `gateway/src/health_monitor.py` — periodic probe of marketplace services
- `gateway/src/openapi.py` — OpenAPI 3.1 spec generation from catalog.json
- `gateway/src/middleware.py` — correlation IDs, Prometheus metrics, structured logging
- `gateway/src/signing.py` — Dilithium signing with HMAC-SHA3 fallback
- `gateway/src/db.py` — DSN parser for SQLite/PostgreSQL abstraction
- `gateway/tests/test_webhooks.py` — 4 tests
- `gateway/tests/test_openapi.py` — 2 tests
- `gateway/tests/test_observability.py` — 5 tests

**Modified files (key changes):**
- All routes: `/execute` → `/v1/execute`, `/health` → `/v1/health`, `/pricing` → `/v1/pricing`
- `gateway/src/app.py` — backward-compat 301/307 redirects, new routes
- `gateway/src/lifespan.py` — WebhookManager, SubscriptionScheduler, HealthMonitor, SigningManager added to AppContext
- `gateway/src/routes/execute.py` — sliding window rate limiting, metrics, signing
- `gateway/src/tools.py` — webhook tools, scheduler tool
- `gateway/src/catalog.json` — 5 new tool definitions
- `products/paywall/src/keys.py` — SHA-256 → SHA-3-256
- `products/paywall/src/storage.py` — `rate_events` table, sliding window, `org_id`
- `products/paywall/src/tiers.py` — `burst_allowance` field
- `products/billing/src/storage.py` — `org_id` column
- `products/marketplace/src/storage.py` — `org_id` column
- `sdk/src/a2a_client/client.py` — `/v1/` paths, retry, caching, connection pooling
- `sdk/src/a2a_client/models.py` — typed response dataclasses
- `sdk/src/a2a_client/errors.py` — `RetryableError`

**Bugs fixed during implementation:**
1. `webhooks.py` didn't strip `sqlite:///` prefix → fixed
2. `test_edge_cases.py` / `test_trust_marketplace.py` still had old paths → updated
3. SDK test fixture missing new client attributes → added

---

## Session 1 (cont.) — Commit, Deploy Script, Cloudflare

### Prompt

> Commit changes with a descriptive commit message. Provide instructions for human on how to deploy the products to make them available for agents to find and buy. Where will this be hosted? I don't have a public server right now -- please post steps on how to set up everything from scratch on a clean ubuntu 24.04 machine. Generate a shell script deploy.sh that automates most of the deployment, and prints clear instructions on how to deploy secrets.

### Response

- **Commit**: `29fd7c7` on `main` — 35 files changed, 2646 insertions(+), 121 deletions(-)
- **Created**: `deploy.sh` (436 lines) — fully automated Ubuntu 24.04 deployment
  - Python 3.12, nginx, certbot, sqlite3, ufw
  - systemd service, nginx reverse proxy, firewall
  - daily SQLite backup cron, initial admin API key
  - prints final instructions for DNS, HTTPS, secrets

### Prompt

> I am setting up the domain through CloudFlare. Do I want the traffic proxied through CloudFlare?

### Response

Yes — use Cloudflare proxy (orange cloud). Recommendations:
- Skip certbot, use Cloudflare Origin Certificate instead
- SSL/TLS mode: Full (Strict)
- UFW: restrict port 443 to Cloudflare IP ranges only
- Provided nginx config for origin cert

---

## Session 1 (cont.) — Agent Provisioning Discussion

### Prompt

> Is there a way to automate the "setting up of a new domain for AI agents"? If AI agents want to publish their a2a services autonomously, can they do it? Is it possible for us to create a service for the AI agents to get the new domain + VPS set up?

### Response

Outlined 3 tiers:
- **Tier 1**: Directory listing (already works via `register_service`)
- **Tier 2**: Wildcard subdomain on shared gateway (recommended, cheap — `agent-name.api.greenhelix.net`)
- **Tier 3**: Dedicated VPS per agent (expensive, full isolation)

### Prompt

> No need for now, thank you.

---

## Session 1 (cont.) — CMO Analysis + E2E Tests

### Prompt

> Can you have the CMO analyze current products, market and product-market-fit and suggest next products or extensions to the existing products. Also have the CTO implement end-to-end tests assuming against a live domain api.greenhelix.net (which doesn't exist yet) to make sure the server is serving and products are setup and accessible (once the domain is live).

### Response

**CMO Analysis** → `CMO_ANALYSIS.md` (573 lines):
- 21 gateway tools cataloged across 6 services
- Payments rated 5/5 PMF, Trust 4/5, Billing 4/5
- #1 blocker: no fiat on-ramp (can't buy credits with real money)
- 12 next products recommended (P0: fiat on-ramp, subscription tools, metered connectors; P1: agent identity, provider analytics, dispute engine, TypeScript SDK; P2: agent reputation, SLA enforcement, split payments, messaging, analytics)
- 90-day revenue projection: $370 → $1,400 → $3,900 MRR

**E2E Tests** → `e2e_tests.py` (1366 lines, 48 tests):
- Standalone script: `A2A_API_KEY=xxx python e2e_tests.py`
- 12 categories: Infrastructure, Auth, Billing, Payments, Marketplace, Trust, Webhooks, Events, Rate Limiting, Signing, Error Handling, Free Tier, Audit, SDK
- Flags: `--dry-run`, `--verbose`, `--timeout N`
- Colored output, unique run isolation, cleanup, graceful skip

---

## Next TODOs

### P0 — Ship Within 30 Days (Revenue Enablers)

- [ ] **Fiat on-ramp via Stripe Checkout** — Let developers buy credits with a credit card. The `deposit()` tool exists; needs a Stripe Checkout session that triggers it on payment confirmation. **This unlocks all revenue.**
- [ ] **Expose subscription tools via gateway** — `create_subscription`, `cancel_subscription`, `get_subscription`, `list_subscriptions`, `reactivate_subscription`. PaymentEngine already implements all of these — just needs catalog.json + tools.py wiring.
- [ ] **Route connectors through gateway** — Meter the Stripe/GitHub/PostgreSQL MCP connectors through `/v1/execute` with billing and rate limiting. 23 additional billable tools.
- [ ] **Deploy to production** — Provision Ubuntu 24.04 VPS, point `api.greenhelix.net` DNS through Cloudflare, run `deploy.sh`, configure origin certificate, fill in `.env` secrets, run `e2e_tests.py` to verify.

### P1 — Ship Within 60 Days (Product Completeness)

- [ ] **Agent identity and authentication** — Cryptographic agent identity (Ed25519 key pairs). Currently any agent can claim any `agent_id`. Security-critical gap.
- [ ] **Provider analytics API** — `get_service_analytics`, `get_revenue_report`, `get_sla_compliance`. Supply-side retention.
- [ ] **Dispute resolution engine** — `open_dispute`, `respond_to_dispute`, `resolve_dispute`. Automated resolution using trust/probe data.
- [ ] **TypeScript/JavaScript SDK** — Port Python SDK to TypeScript, publish to npm as `@a2a/client`. Doubles addressable market.

### P2 — Ship Within 90 Days (Competitive Moats)

- [ ] **Agent reputation score** — Consumer-side trust (payment reliability, dispute history, volume).
- [ ] **SLA enforcement engine** — Verify claimed SLAs against probe data, auto-flag violations.
- [ ] **Multi-party payment splits** — `create_split_intent` for marketplace take rates and referral commissions.
- [ ] **Agent-to-agent messaging/negotiation** — Typed message protocol for price negotiation, task specification.
- [ ] **Analytics suite** — Real-time dashboards, alerting, developer-facing analytics.

### Infrastructure

- [ ] **Add Swagger UI** — Serve interactive API explorer at `/docs` using the existing OpenAPI spec.
- [ ] **Hosted sandbox** — `sandbox.greenhelix.net` with pre-provisioned free-tier keys for instant onboarding.
- [ ] **PostgreSQL migration** — When write throughput exceeds ~100 TPS. DSN abstraction layer is ready.
- [ ] **CI/CD pipeline** — GitHub Actions for test + deploy on push to main.


---

## Session 2 — 2026-03-27 (Overnight): Identity, Pricing, Customer Agent

### Prompt

> Continue with implementing the TODOs above, following up on CMO_ANALYSIS.md. Use TDD for implementation as much as possible:
> * Promote 5.4 (Agent Identity and Authentication) and 5.8 (Agent Reputation Score) to higher priority. Research and consider ZK-proofs in the implementation if suitable.
> * Focus on building domain-specific trust layer on top of identity. E.g. for trading bots. Build Agent Reputation + Execution Verification Layer, with PnL verification, latency scoring, signal accuracy tracking
> * Update pricing per 4.1 Pricing Strategy Critique.
> * Create a new agent -- an incidental customer -- and let it explore the products and gather feedback.
> * Keep documentation in-code, with on-demand documentation generation.
>
> Human is going to bed now -- work autonomously and iteratively, and provide a detailed report when done, with details on the agent identity schema for trading bots. As a CMO, review the report and consider existing products in the domain of trading bots.

### Response

**4 major items implemented overnight. 730 tests passing across 9 modules.**

#### 1. Agent Identity System (`products/identity/`) — NEW PRODUCT

- Ed25519 keypair generation + signature verification
- SHA3-256 hiding commitments for trading bot metrics (Sharpe, DD, PnL, latency, signal accuracy, win rate, trade count, AUM)
- Platform auditor attestations (Ed25519 signed, 7-day validity)
- Verified claims ("Sharpe >= 2.15", "MaxDD <= 3.2%")
- Consumer-side reputation scoring (payment reliability, data source quality, volume)
- 6 new gateway tools: `register_agent`, `verify_agent`, `submit_metrics`, `get_agent_identity`, `get_verified_claims`, `get_agent_reputation`
- 40 product tests + 7 gateway integration tests

ZK-proof research: Full ZK is overkill for MVP (no production Python libraries, circuit authoring too complex). Implemented hiding commitments + signed attestations instead. Migration path to Bulletproofs (month 3-6) and ZK circuits (month 6-12) documented.

#### 2. Pricing Update

- Added **Starter tier** (1,000/hr, 25 burst, 7-day audit, community support)
- Removed per-call surcharge from Pro/Enterprise ($1.00 → $0.00)
- Switched `create_intent` to **2% of amount** (min $0.01, max $5.00)
- Switched `create_escrow` to **1.5% of amount** (min $0.01, max $10.00)
- `capture_intent` and `release_escrow` now free (fee at creation)
- Added `calculate_tool_cost()` helper to execute route

#### 3. Customer Agent Simulation (AlphaBot-v3)

- Exercised all 28 tools across all modules: 107 API calls, 97 passed
- NPS scores: Infrastructure 8, Payments 7, Metrics 7, Webhooks 7, Billing 6, Marketplace 6, Identity 6, Trust 5, Rate Limiting 5, Admin 5
- Key gaps identified: no self-service onboarding, no subscription tools, no withdraw, no dispute resolution, no cross-agent metric search
- Full report: `CUSTOMER_AGENT_FEEDBACK.md`

#### 4. CMO Review: Trading Bot Market

- No competitor offers crypto-verified performance claims for trading bots
- Differentiation: commitment-based metrics + escrow-backed signal purchases + trust scoring
- Key competitors analyzed: Collective2, QuantConnect, Numerai, 3Commas
- Top P0 recommendations: expose subscription tools, cross-agent metric search, self-service wallet

**Detailed report**: `OVERNIGHT_REPORT_20260327.md`

### Files Created
- `products/identity/` — 8 source files, 3 test files (1,501 lines)
- `gateway/tests/test_identity.py` — 7 integration tests
- `customer_agent_report.py` — 1,709 lines (simulation script)
- `CUSTOMER_AGENT_FEEDBACK.md` — 578 lines
- `OVERNIGHT_REPORT_20260327.md` — overnight report

### Files Modified
- `products/paywall/src/tiers.py` — Starter tier, removed surcharges
- `gateway/src/catalog.json` — 6 identity tools, percentage pricing
- `gateway/src/routes/execute.py` — `calculate_tool_cost()` for percentage pricing
- `gateway/src/tools.py` — 6 identity tool functions
- `gateway/src/lifespan.py` — IdentityAPI in AppContext
- `gateway/src/bootstrap.py` — identity product namespace
- `gateway/tests/conftest.py` — IDENTITY_DSN
- `gateway/tests/test_integration.py` — Updated fee assertions

---

## Next TODOs (Updated from Customer Feedback)

### P0 — Immediate

- [ ] **Expose subscription tools** — `create_subscription`, `cancel_subscription`, etc. (engine exists)
- [ ] **Self-service wallet creation** — `create_wallet` tool
- [ ] **Cross-agent metric search** — `search_agents_by_metrics` tool (find bots with Sharpe > 2.0)
- [ ] **Fix submit_metrics error handling** — return 400 not 500 for invalid metric names
- [ ] **Fiat on-ramp** — Stripe Checkout → deposit
- [ ] **Deploy to production** — api.greenhelix.net

### P1 — Next Sprint

- [ ] **Withdraw/payout** tool
- [ ] **Performance-gated escrow** — auto-release based on verified metrics
- [ ] **Dispute resolution engine**
- [ ] **TypeScript SDK**
- [ ] **Key rotation** — `rotate_key` tool
- [ ] **Metered connectors** — route Stripe/GitHub/PostgreSQL through gateway

### P2 — Backlog

- [x] ~~Agent Identity and Authentication~~ (DONE — Session 2)
- [x] ~~Agent Reputation Score~~ (DONE — Session 2)
- [x] ~~Pricing update~~ (DONE — Session 2)
- [ ] **Historical claim chain** — Merkle tree of attestations
- [ ] **Agent-to-agent messaging/negotiation**
- [ ] **SLA enforcement automation**
- [ ] **Bulletproofs range proofs** (Rust FFI)
- [ ] **Strategy marketplace vertical**
- [ ] **Analytics suite**
- [ ] **Multi-party payment splits**

### Infrastructure

- [ ] **Add Swagger UI** — `/docs` endpoint
- [ ] **Hosted sandbox** — `sandbox.greenhelix.net`
- [ ] **PostgreSQL migration** — DSN abstraction ready
- [ ] **CI/CD pipeline** — GitHub Actions
