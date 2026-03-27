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

---

## Session 3 — 2026-03-27: Full TODO Processing (15 Items)

### Prompt

> Process the latest todos in MASTER_LOG.md (from customer feedback), in order. Skip the todos needed production/live API. TDD preferred.

### Response

**15 items implemented. 833 tests passing across 10 modules (was 730).**

#### P0 — Immediate (4 items)

| # | Item | Status | New Tests |
|---|------|--------|-----------|
| 1 | Expose subscription tools (5 tools) | DONE | 6 |
| 2 | Self-service wallet creation + withdraw | DONE | 5 |
| 3 | Cross-agent metric search | DONE | 3 |
| 4 | Fix submit_metrics error handling (400 not 500) | DONE | 1 |

#### P1 — Next Sprint (3 items)

| # | Item | Status | New Tests |
|---|------|--------|-----------|
| 5 | Performance-gated escrow | DONE | 3 |
| 6 | Dispute resolution engine | DONE | 4 |
| 7 | Key rotation tool | DONE | 2 |

#### P2 — Backlog (7 items)

| # | Item | Status | New Tests |
|---|------|--------|-----------|
| 8 | Historical claim chain (Merkle tree) | DONE | 32 (identity product) |
| 9 | Agent-to-agent messaging | DONE | 35 (new module) |
| 10 | SLA enforcement automation | DONE | 1 |
| 11 | Strategy marketplace vertical | DONE | 1 |
| 12 | Analytics suite | DONE | 2 |
| 13 | Multi-party payment splits | DONE | 2 |
| 14 | Swagger UI at /docs | DONE | 1 |

#### Skipped (need production/live API)

- Fiat on-ramp (Stripe Checkout)
- Deploy to production
- TypeScript SDK (npm ecosystem)
- Metered connectors (Stripe/GitHub/PostgreSQL)

### New Files Created

- `gateway/src/disputes.py` — DisputeEngine (open/respond/resolve against escrows)
- `gateway/src/swagger.py` — Swagger UI HTML handler
- `gateway/tests/test_subscriptions.py` — 6 subscription tests
- `gateway/tests/test_wallet_tools.py` — 5 wallet tests
- `gateway/tests/test_metric_search.py` — 3 cross-agent search tests
- `gateway/tests/test_performance_escrow.py` — 3 performance escrow tests
- `gateway/tests/test_disputes.py` — 4 dispute tests
- `gateway/tests/test_key_rotation.py` — 2 key rotation tests
- `gateway/tests/test_p2_features.py` — 12 P2 feature tests
- `products/messaging/` — NEW MODULE (8 source files, 3 test files, 35 tests)

### Modified Files

- `gateway/src/tools.py` — 20 new tool functions, registry expanded to 49 tools
- `gateway/src/catalog.json` — 20 new tool definitions (49 total)
- `gateway/src/errors.py` — Added InvalidMetricError→400, ValueError→400, dispute/subscription errors
- `gateway/src/lifespan.py` — Added MessagingAPI, DisputeEngine to AppContext
- `gateway/src/bootstrap.py` — Added messaging product bootstrap
- `gateway/src/app.py` — Added /docs Swagger UI route
- `gateway/tests/conftest.py` — Added DISPUTE_DSN, MESSAGING_DSN
- `gateway/tests/test_identity.py` — Added submit_metrics 400 error test
- `products/identity/src/storage.py` — Added search_claims(), claim_chains table
- `products/identity/src/api.py` — Added search_agents_by_metrics(), build_claim_chain()
- `products/identity/src/crypto.py` — Added MerkleTree class

### Test Summary

```
billing     103 passed
paywall     106 passed
payments    164 passed
marketplace 128 passed
trust       103 passed
identity     72 passed  (+32 from Merkle tree)
messaging    35 passed  (NEW)
gateway     111 passed  (+36 from new tools)
sdk          11 passed
────────────────────────────
TOTAL       833 passed  (+103 from Session 2)
```

### Tool Catalog Summary (49 tools)

| Service | Tools | Count |
|---------|-------|-------|
| billing | get_balance, get_usage_summary, deposit, create_wallet, withdraw, get_service_analytics, get_revenue_report | 7 |
| payments | create_intent, capture_intent, create_escrow, release_escrow, get_payment_history, create_subscription, cancel_subscription, get_subscription, list_subscriptions, reactivate_subscription, process_due_subscriptions, create_performance_escrow, check_performance_escrow, create_split_intent | 14 |
| marketplace | search_services, best_match, register_service, list_strategies | 4 |
| trust | get_trust_score, search_servers, delete_server, update_server, check_sla_compliance | 5 |
| identity | register_agent, verify_agent, submit_metrics, get_agent_identity, get_verified_claims, get_agent_reputation, search_agents_by_metrics, build_claim_chain, get_claim_chains | 9 |
| messaging | send_message, get_messages, negotiate_price | 3 |
| disputes | open_dispute, respond_to_dispute, resolve_dispute | 3 |
| events | publish_event, get_events | 2 |
| webhooks | register_webhook, list_webhooks, delete_webhook | 3 |
| paywall | get_global_audit_log, rotate_key | 2 |

---

## Next TODOs (Remaining)

### Requires Production/Live API

- [ ] **Fiat on-ramp** — Stripe Checkout → deposit
- [ ] **Deploy to production** — api.greenhelix.net
- [ ] **TypeScript SDK** — port to npm
- [ ] **Metered connectors** — route Stripe/GitHub/PostgreSQL through gateway

### Infrastructure

- [ ] **Hosted sandbox** — `sandbox.greenhelix.net`
- [ ] **PostgreSQL migration** — DSN abstraction ready
- [ ] **CI/CD pipeline** — GitHub Actions

### Future (from CMO analysis)

- [ ] **Bulletproofs range proofs** (Rust FFI)
- [x] ~~Agent Identity and Authentication~~ (DONE — Session 2)
- [x] ~~Agent Reputation Score~~ (DONE — Session 2)
- [x] ~~Pricing update~~ (DONE — Session 2)
- [x] ~~Subscription tools~~ (DONE — Session 3)
- [x] ~~Self-service wallet~~ (DONE — Session 3)
- [x] ~~Cross-agent metric search~~ (DONE — Session 3)
- [x] ~~Dispute resolution~~ (DONE — Session 3)
- [x] ~~Performance-gated escrow~~ (DONE — Session 3)
- [x] ~~Historical claim chain~~ (DONE — Session 3)
- [x] ~~Agent messaging~~ (DONE — Session 3)
- [x] ~~SLA enforcement~~ (DONE — Session 3)
- [x] ~~Strategy marketplace~~ (DONE — Session 3)
- [x] ~~Analytics suite~~ (DONE — Session 3)
- [x] ~~Multi-party splits~~ (DONE — Session 3)
- [x] ~~Swagger UI~~ (DONE — Session 3)
- [x] ~~Key rotation~~ (DONE — Session 3)


## Prompt (Session 3, continued)
* Commit changes. Always commit changes at the end of work.
* Assume role of senior software architect. Review Agent Identity design, and produce a report on strong and weak points, technical debt, possible extensions/generalizations, future-proofing, etc. Create actionable todo list but do not change code yet.

---

## Senior Architect Review: Agent Identity System

**Reviewer**: Senior Software Architect (automated)
**Date**: 2026-03-27
**Scope**: `products/identity/src/` — models.py (81 LOC), crypto.py (309 LOC), api.py (384 LOC), storage.py (482 LOC)
**Test Coverage**: 72 tests across test_crypto.py, test_api.py, test_storage.py

---

### 1. Strong Points

**1.1 Cryptographic Foundation — Ed25519 + SHA3-256**
- Correct choice. Ed25519 is compact (32-byte keys, 64-byte sigs), fast, and deterministic (no nonce reuse risk unlike ECDSA). The `cryptography` library is the gold-standard Python wrapper.
- SHA3-256 for commitments/Merkle trees avoids length-extension attacks that plague SHA-256. Good forward-looking choice.
- Attestation signing uses JSON canonical form (`sort_keys=True, separators=(",",":")`) — prevents signature malleability from key ordering or whitespace.

**1.2 Commitment Scheme Design**
- Hiding commitments with 32-byte random blinding factors provide statistical hiding — the commitment reveals nothing about the value without the blinding factor.
- Integer scaling (`int(value * 10000)`) before hashing avoids floating-point representation ambiguity across platforms.
- Metric-name binding in the hash preimage prevents cross-metric commitment substitution (e.g., reusing a Sharpe commitment as a drawdown commitment).

**1.3 Clean Separation of Concerns**
- 4-file architecture (models / crypto / api / storage) is well-factored. Crypto operations are pure/stateless, storage is async I/O, API orchestrates.
- Pydantic models with `Field(ge=, le=)` validators catch bad data at the boundary.
- The dataclass-based `IdentityAPI` with dependency injection (`storage`, `auditor_private_key`) is test-friendly.

**1.4 Merkle Claim Chains**
- Correct implementation of binary Merkle tree with proof generation and verification.
- Odd-leaf-count handling (duplicate last leaf) follows standard convention.
- `compute_proof` + `verify_proof` roundtrip is thoroughly tested (7 edge cases including tampering).

**1.5 Test Quality**
- 72 tests with strong coverage: edge cases (empty tree, single leaf, wrong key, tampered sigs, expired attestations), error paths (AgentNotFoundError, InvalidMetricError, IndexError).
- TDD approach is evident — test class structure maps directly to feature classes.

---

### 2. Weak Points

**2.1 CRITICAL — Blinding Factor Discarded (Commitment Scheme Broken)**
In `api.py:147`:
```python
commit_hash, _blinding = AgentCrypto.create_commitment(value, metric_name)
```
The blinding factor is created then **immediately discarded** (`_blinding`). This means:
- The agent can never open (reveal) the commitment to prove the value.
- The commitment scheme becomes one-way — it's a hash, not a usable commitment.
- `verify_commitment()` in crypto.py exists but is **unreachable** in practice because no one has the blinding factor.

**Severity**: CRITICAL — the entire commitment/reveal protocol is non-functional.
**Fix**: Store blinding factors in a `commitment_secrets` table (encrypted at rest, accessible only to the committing agent or auditor).

**2.2 HIGH — No Commitment Reveal/Open Protocol**
Related to 2.1: there is no `open_commitment()` or `reveal_metrics()` API method. The design has `create_commitment` and `verify_commitment` but no workflow that connects them. A consumer cannot verify that a claimed Sharpe of 2.35 actually matches the commitment hash.

**2.3 HIGH — Auditor Key is Ephemeral**
In `api.py:52-57`:
```python
def __post_init__(self) -> None:
    if not self.auditor_private_key:
        priv, pub = AgentCrypto.generate_keypair()
```
The platform auditor keypair is auto-generated on every `IdentityAPI` instantiation. This means:
- After a server restart, all existing attestation signatures become **unverifiable** (new public key, old signatures).
- No key rotation protocol — old keys are simply lost.
- The auditor public key isn't published or discoverable by consumers.

**Severity**: HIGH — attestation verification breaks across restarts.
**Fix**: Persist auditor keypair (env var, vault, or DB), add key rotation with validity periods, publish public key at a well-known endpoint.

**2.4 HIGH — No Private Key Management for Agents**
In `api.py:72-73`:
```python
if public_key is None:
    _private_key, public_key = AgentCrypto.generate_keypair()
```
When auto-generating, the private key is discarded (`_private_key`). The agent never receives it. This means:
- Auto-registered agents can never sign anything (their private key is lost).
- `verify_agent()` will always fail for auto-registered agents since no one can produce a valid signature.

**Severity**: HIGH — auto-registration is broken as an identity mechanism.
**Fix**: Return the private key to the caller (and only the caller) on registration. Never store private keys server-side.

**2.5 MEDIUM — Reputation Model is Placeholder**
`compute_reputation()` uses attestation count and data source as proxies for payment reliability and dispute rate. The field names are misleading:
- `payment_reliability` is actually "attestation count × 10"
- `dispute_rate` is actually "average data source quality score" (higher = better, contrary to the name "dispute_rate")
- No actual payment or dispute data is consulted

**2.6 MEDIUM — No Attestation Revocation**
Attestations can only expire (7-day TTL). There is no mechanism to:
- Revoke a compromised attestation before expiry
- Blacklist a fraudulent agent's claims
- Update an attestation when new data contradicts it

**2.7 MEDIUM — VerifiedClaim.attestation_signature Not Round-Trippable**
In `storage.py:310`:
```python
attestation_signature="",  # Not stored directly; linked via attestation_id
```
Claims are stored with `attestation_id` (FK) but reconstructed with empty `attestation_signature`. The Pydantic model says the field should be the signature, but it's blank after retrieval. This breaks any downstream code that relies on `claim.attestation_signature`.

**2.8 LOW — No Pagination for search_claims**
`search_claims()` accepts `limit` but no `offset`/cursor. For a marketplace with thousands of agents, the first page is all you get.

**2.9 LOW — SQLite DSN Parsing is Fragile**
```python
db_path = self.dsn.replace("sqlite:///", "")
```
Only handles `sqlite:///` prefix. `:memory:` DSNs, relative paths, or `sqlite://` (2 slashes) will produce wrong paths.

---

### 3. Technical Debt

| ID | Item | Severity | Effort |
|----|------|----------|--------|
| TD-1 | Blinding factors discarded — commitment/reveal broken | Critical | M |
| TD-2 | Auditor keypair ephemeral — signatures unverifiable after restart | High | S |
| TD-3 | Agent private keys discarded on auto-registration | High | S |
| TD-4 | `attestation_signature` empty on claim retrieval from DB | Medium | S |
| TD-5 | `dispute_rate` field name is semantically inverted | Medium | S |
| TD-6 | No attestation revocation mechanism | Medium | M |
| TD-7 | No pagination (offset/cursor) on search endpoints | Low | S |
| TD-8 | Fragile DSN parsing | Low | XS |
| TD-9 | `store_identity` uses INSERT OR REPLACE — silently overwrites keys | Medium | S |
| TD-10 | No index on `verified_claims(metric_name)` — search_claims scans | Low | XS |

---

### 4. Possible Extensions / Generalizations

**4.1 Decentralized Identity (DID) Compatibility**
The current `agent_id` is an opaque string. Mapping to W3C DID format (`did:a2a:<agent_id>`) would:
- Enable interoperability with external identity systems
- Allow agents to bring their own identity from other platforms
- Support DID Documents for key discovery

**4.2 Verifiable Credentials (VC) Standard**
Attestations are semantically identical to W3C Verifiable Credentials. Aligning the data model would:
- Make claims portable across platforms
- Enable standard VC wallets to hold agent credentials
- Support JSON-LD proof formats

**4.3 Zero-Knowledge Range Proofs**
Current claims are binary (gte/lte). With Bulletproofs or similar:
- An agent could prove "my Sharpe > 2.0" without revealing the exact value
- Commitment scheme becomes actually useful (currently broken per 2.1)
- Eliminates the need for a trusted auditor to vouch for exact values

**4.4 Multi-Auditor Attestation (Threshold Signatures)**
Currently a single platform auditor signs everything. Multi-auditor would:
- Require k-of-n auditors to agree (threshold Ed25519 or Schnorr)
- Remove single point of trust failure
- Enable third-party auditors (exchanges, analytics providers)

**4.5 Temporal Reputation with Decay**
Current reputation is a snapshot. A time-series model would:
- Weight recent attestations more heavily
- Detect reputation degradation trends
- Support "reputation velocity" as a signal

**4.6 Cross-Platform Claim Portability**
Merkle claim chains could be anchored to a public blockchain or timestamping service:
- Provides tamper-evident proof without trusting the platform
- Enables agents to prove their history to third parties
- Would require anchoring the Merkle root periodically (e.g., Bitcoin OP_RETURN, Ethereum event log)

**4.7 Metric Composition**
Allow composite metrics ("risk-adjusted alpha") that combine multiple base metrics with defined formulas. This would enable:
- Custom scoring models per marketplace
- Normalized comparison across different strategy types
- Derived claims from base claims

---

### 5. Future-Proofing Assessment

| Dimension | Current State | Risk | Recommendation |
|-----------|---------------|------|----------------|
| **Algorithm agility** | Hardcoded Ed25519 + SHA3-256 | Low | Good choices, but add `algorithm` field to attestations for future rotation |
| **Key rotation** | None | High | Implement key versioning with validity periods |
| **Storage backend** | SQLite only | Medium | Already have DSN pattern; add abstract storage interface |
| **Metric schema** | Hardcoded set of 8 | Medium | Move to registry pattern; allow per-marketplace custom metrics |
| **Attestation format** | Custom JSON | Medium | Align with W3C VC for interop; add `version` field now |
| **Multi-tenancy** | `org_id` field exists but unused in queries | Low | Already scaffolded; just needs query filters |
| **Scale** | In-memory SQLite per test, single-file prod | High | OK for MVP; needs connection pooling + PostgreSQL for >100 agents |
| **Claim expiry** | 7-day fixed TTL | Medium | Make TTL configurable per metric and per tier |

---

### 6. Actionable TODO List

**P0 — Must Fix (Correctness Broken)**

- [ ] **TODO-1**: Store blinding factors — add `commitment_secrets` table, return blinding to agent on `submit_metrics`, add `reveal_commitment(agent_id, metric_name, blinding)` API method
- [ ] **TODO-2**: Persist auditor keypair — load from env `AUDITOR_PRIVATE_KEY` / `AUDITOR_PUBLIC_KEY`, fall back to DB storage, add startup validation
- [ ] **TODO-3**: Return agent private key on auto-registration — modify `register_agent()` return type to include private key when auto-generated (one-time, never stored server-side)

**P1 — Should Fix (Data Integrity / Semantics)**

- [ ] **TODO-4**: Fix `attestation_signature` round-trip — join claims with attestations table on retrieval, populate the field correctly
- [ ] **TODO-5**: Rename `dispute_rate` to `data_source_quality` or split reputation model into clearly-named sub-scores
- [ ] **TODO-6**: Change `store_identity` from INSERT OR REPLACE to INSERT with conflict detection — raise `AgentAlreadyExistsError` on duplicate
- [ ] **TODO-7**: Add `CREATE INDEX idx_claim_metric ON verified_claims(metric_name)` for search_claims performance
- [ ] **TODO-8**: Add `version` field to AuditorAttestation model (default "1.0") for format evolution

**P2 — Should Add (Protocol Completeness)**

- [ ] **TODO-9**: Implement attestation revocation — add `revoked_at` column, `revoke_attestation(attestation_id, reason)` API, filter revoked in all queries
- [ ] **TODO-10**: Add commitment reveal/open workflow — `open_commitment(agent_id, metric_name, value, blinding)` that verifies and publishes the revealed value
- [ ] **TODO-11**: Add pagination (offset + limit or cursor) to `search_claims`, `get_attestations`, `get_commitments`, `get_claim_chains`
- [ ] **TODO-12**: Harden DSN parsing — handle `:memory:`, `sqlite://` (2 slashes), relative paths, and reject unsupported schemes

**P3 — Future Enhancement (Extensibility)**

- [ ] **TODO-13**: Add `algorithm` field to attestation schema (e.g., "ed25519-sha3-256") for crypto agility
- [ ] **TODO-14**: Make metric set configurable — move SUPPORTED_METRICS to storage/config, allow per-org custom metrics
- [ ] **TODO-15**: Implement auditor key rotation — key versioning table, sign attestations with current key, verify against key valid at attestation time
- [ ] **TODO-16**: Align attestation model with W3C Verifiable Credentials structure (issuer, credentialSubject, proof)
- [ ] **TODO-17**: Add Merkle proof endpoint — `get_inclusion_proof(chain_id, attestation_index)` returning sibling path for client-side verification
- [ ] **TODO-18**: Integrate reputation with actual payment/dispute data from billing and dispute engines (replace proxy scores)

---

### 7. Architecture Diagram (Current State)

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│  Gateway     │────▶│ IdentityAPI  │────▶│IdentityStorage │
│  tools.py    │     │  (api.py)    │     │ (storage.py)   │
└─────────────┘     └──────┬───────┘     └────────────────┘
                           │                     │
                    ┌──────▼───────┐       SQLite (6 tables)
                    │ AgentCrypto  │       ├─ agent_identities
                    │ (crypto.py)  │       ├─ metric_commitments
                    │              │       ├─ attestations
                    │ • Ed25519    │       ├─ verified_claims
                    │ • SHA3-256   │       ├─ agent_reputation
                    │ • MerkleTree │       └─ claim_chains
                    └──────────────┘

Data Flow:
  register_agent ──▶ store_identity (public_key only)
  submit_metrics ──▶ create_commitment ──▶ store_commitment
                 ──▶ sign_attestation  ──▶ store_attestation
                 ──▶ create_claim      ──▶ store_claim
  build_chain    ──▶ get_attestations ──▶ MerkleTree.compute_root
                                       ──▶ store_claim_chain
```

### 8. Summary

The Agent Identity system has a **solid cryptographic foundation** (Ed25519, SHA3-256, Merkle trees) and **clean architecture** (4-layer separation, Pydantic validation, async I/O). The test suite is strong at 72 tests with good edge-case coverage.

However, there are **3 critical/high correctness bugs** that make the commitment scheme and identity verification non-functional in practice:
1. Blinding factors are discarded (commitments can never be opened)
2. Auditor keys are ephemeral (attestations unverifiable after restart)
3. Agent private keys are discarded on auto-registration (agents can't sign)

These must be fixed before the identity system can be used for any trust-critical workflow. The remaining technical debt is manageable and the extension points (DID, VC, ZK proofs, multi-auditor) are well-positioned by the current abstractions.

**Overall assessment**: Strong MVP skeleton, correct crypto primitives, but the **protocol-level plumbing** that connects the primitives into a usable trust workflow is incomplete. Fix P0 items first, then P1 for data integrity, before pursuing any extensions.


## Prompt
* Store the above diagram in a format that's easily machine-updateable and that can be converted into a pretty printed diagram easily (grahviz/dot? whatever lightweight tool is available).
* Implement all todos in the list, in order (follow TDD principles)
