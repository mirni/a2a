# PLAN v2 -- Implementation Session Plan

**Date:** 2026-03-31
**Role:** CTO
**Context:** Synthesized from 25 customer agent reports (v2, 13,910 lines), MASTER_LOG.md (18 sessions), previous architecture reviews, and Round 4 live testing.
**Platform:** A2A Commerce Gateway v0.4.9, 125 tools, 15 services, ~1,800 tests

---

## Status Key

- [ ] Not started
- [~] In progress
- [x] Done

---

## P0 -- Security Critical

These are CVSS 9.0+ findings from the v2 customer reports. Several overlap with items already partially addressed (ownership validation added in Session TODO Items 1-14), but gaps remain.

### P0-1: Restrict `pg_execute` to parameterized SELECT-only
**Source:** Customer Report S-01 (CVSS 9.8), Agent 2/15
**Current state:** `pg_execute` allows arbitrary SQL including DDL/DCL (CREATE, DROP, GRANT). No statement allowlisting, params optional.
**Action:**
- [x] Add SQL statement parser/allowlist: only SELECT, INSERT, UPDATE, DELETE
- [x] Block DDL (CREATE, ALTER, DROP) and DCL (GRANT, REVOKE) statements
- [x] Require parameterized queries (params must be non-empty for INSERT/UPDATE/DELETE)
- [x] Add tests for SQL injection vectors via pg_execute
**Files:** `gateway/src/tools/connectors.py` (or equivalent postgres tool), tests

### P0-2: Verify and harden ownership validation on financial ops
**Source:** Customer Report S-02 (CVSS 9.8), C-2/C-3
**Current state:** `authorization.py` was added in Session TODO Items (enforces agent_id match on 36 tools). Need to verify coverage is complete per v2 report findings -- specifically `withdraw`, `freeze_wallet`, `capture_intent`, `release_escrow`, `cancel_escrow`, `refund_intent`.
**Action:**
- [x] Audit `authorization.py` guard coverage against v2 report tool list
- [x] Add negative tests: agent A cannot withdraw from agent B's wallet
- [x] Add negative tests: agent A cannot capture agent B's intent
- [x] Verify freeze/unfreeze wallet requires admin scope
**Files:** `gateway/src/authorization.py`, `gateway/tests/test_authorization.py`

### P0-3: Fix freeze_wallet/unfreeze_wallet tier and access control
**Source:** Customer Report S-04 (CVSS 9.1), C-4
**Current state:** These are at free tier with no admin role check. Any agent can freeze any wallet.
**Action:**
- [x] Move `freeze_wallet`/`unfreeze_wallet` to pro or enterprise tier in `catalog.json`
- [x] Require admin scope on the API key to invoke these tools
- [x] Add tests: non-admin cannot freeze, admin can freeze
**Files:** `gateway/src/catalog.json`, `gateway/src/tools/billing.py`, tests

### P0-4: Validate webhook URLs against SSRF
**Source:** Customer Report S-05 (CVSS 8.6), Agent 2/10
**Current state:** `register_webhook` and `test_webhook` accept arbitrary URLs. Can target RFC 1918 ranges, link-local, cloud metadata (169.254.169.254).
**Action:**
- [x] Create URL validator that blocks: private IPs (10.x, 172.16-31.x, 192.168.x), localhost, link-local (169.254.x), cloud metadata endpoints
- [x] Apply validator in `register_webhook` and `test_webhook`
- [x] Add tests for each blocked IP range
**Files:** `gateway/src/webhooks.py` or `gateway/src/tools/infrastructure.py`, tests

### P0-5: Fix backup_database key leak and restore_database path traversal
**Source:** Customer Report S-06 (CVSS 8.6), Agent 2/12
**Current state:** `backup_database` returns Fernet encryption key in response body. `restore_database` accepts arbitrary `file_path` parameter.
**Action:**
- [x] Remove encryption key from `backup_database` response (store server-side only)
- [x] Sanitize `restore_database` file_path: reject `..`, absolute paths, only allow filenames from backup directory
- [x] Move admin tools to enterprise tier (or require admin scope)
- [x] Add tests for path traversal attempts
**Files:** `gateway/src/tools/admin.py` (or equivalent), tests

### P0-6: Prevent create_api_key tier escalation
**Source:** Customer Report S-07 (CVSS 8.1)
**Current state:** Caller-supplied `tier` parameter may allow self-upgrade (free caller creating pro key).
**Action:**
- [x] Enforce: callers can only create keys at their own tier or below
- [x] Add test: free-tier agent cannot create pro-tier key
**Files:** `gateway/src/tools/paywall.py`, tests

### P0-7: Fix resolve_dispute impersonation
**Source:** Customer Report S-08 (CVSS 8.1)
**Current state:** `resolve_dispute` accepts caller-supplied `resolved_by` field -- allows impersonation.
**Action:**
- [x] Override `resolved_by` with the authenticated agent_id from the API key
- [x] Add test: resolved_by field is ignored and replaced with caller identity
**Files:** `gateway/src/tools/disputes.py` (or equivalent), tests

---

## P1 -- Database / Data Integrity Bugs

These are the persistent OperationalError bugs from Round 4 and data integrity findings from the v2 report.

### P1-1: Fix payments DB schema (capture_intent, release_escrow, partial_capture)
**Source:** Round 4 Customer Feedback, Customer Report H-2
**Current state:** All three return `OperationalError`. Likely missing columns in payments DB that were added to DDL but never migrated on existing DBs.
**Action:**
- [x] Identify missing columns in payments storage (check `_SCHEMA` vs actual DB)
- [x] Write migration(s) using the `Migration` framework from `products/shared/src/migrate.py`
- [x] Add `_MIGRATIONS` to payments `StorageBackend`
- [x] Update `_SCHEMA` DDL to reflect final state
- [x] Add migration regression tests (old-schema -> new-schema)
- [x] Verify capture_intent, release_escrow, partial_capture work end-to-end
**Files:** `products/payments/src/storage.py`, `products/payments/tests/test_migrations.py`

### P1-2: Fix messaging DB schema (send_message, negotiate_price)
**Source:** Round 4 Customer Feedback
**Current state:** Both return `OperationalError`. Same root cause as P1-1 -- missing columns.
**Action:**
- [x] Identify missing columns in messaging storage
- [x] Write migration(s) using Migration framework
- [x] Add `_MIGRATIONS` to messaging `StorageBackend`
- [x] Add migration regression tests
- [x] Verify send_message and negotiate_price work
**Files:** `products/messaging/src/storage.py`, `products/messaging/tests/test_migrations.py`

### P1-3: Fix get_exchange_rate (UnsupportedCurrencyError)
**Source:** Round 4 Customer Feedback (SkyScout, FinanceBot, TravelMate)
**Current state:** Returns `UnsupportedCurrencyError` for ALL currency pairs despite schema advertising 6 currencies.
**Action:**
- [x] Debug `get_exchange_rate` tool: check if exchange rate service is wired up correctly
- [x] Verify `ExchangeRateService` has rate data loaded (may need seed rates)
- [x] Add tests: USD->EUR, BTC->USD, CREDITS->USD all return valid rates
**Files:** `products/billing/src/exchange.py`, `gateway/src/tools/billing.py`, tests

### P1-4: Add idempotency_key to more financial write tools
**Source:** Customer Report H-2 (only 3/57 mutating tools have idempotency)
**Current state:** Only `create_intent`, `create_escrow`, `create_subscription` have idempotency_key.
**Action:**
- [x] Add `idempotency_key` to: `deposit`, `withdraw`, `create_split_intent`, `create_performance_escrow`, `refund_settlement`
- [x] Add UNIQUE constraint on idempotency_key in relevant storage tables
- [x] Add tests: duplicate calls with same key return same result
**Files:** Billing storage, payments storage, gateway tools, tests

### P1-5: Make convert_currency atomic
**Source:** Customer Report H-3
**Current state:** Two-phase withdraw-then-deposit. Crash between phases = fund loss.
**Action:**
- [x] Wrap withdraw + deposit in a single DB transaction
- [x] Add test: simulated crash after withdraw rolls back
- [x] Document the atomicity guarantee
**Files:** `products/billing/src/exchange.py` or `tracker.py`, tests

---

## P2 -- Feature Gaps & Functionality

### P2-1: Add `get_budget_cap` tool (set but can't retrieve)
**Source:** Round 4 (FinanceBot), previous MASTER_LOG P1-5
**Action:**
- [x] Add `get_budget_cap` tool or rename `get_budget_status` to include cap values
- [x] Register in catalog.json
- [x] Add tests
**Files:** `gateway/src/tools/billing.py`, `gateway/src/catalog.json`, tests

### P2-2: Expose multi-currency in gateway tools
**Source:** Round 4 (SkyScout), Customer Report M-10/M-14
**Current state:** Multi-currency is implemented in billing but `create_intent`, `create_escrow` have no `currency` parameter in the gateway tool layer.
**Action:**
- [x] Add optional `currency` parameter (default: "CREDITS") to payment tools: `create_intent`, `create_escrow`, `create_subscription`, `create_split_intent`
- [x] Update catalog.json schemas
- [x] Add tests for non-CREDITS currency intents
**Files:** `gateway/src/tools/payments.py`, `gateway/src/catalog.json`, tests

### P2-3: Add `list_intents` and `list_escrows` tools
**Source:** Customer Report M-12, Agent 4/24
**Current state:** No way to enumerate pending intents or escrows for reconciliation.
**Action:**
- [x] Add `list_intents(agent_id, status?, limit?)` tool
- [x] Add `list_escrows(agent_id, status?, limit?)` tool
- [x] Register in catalog.json
- [x] Add tests
**Files:** `products/payments/src/engine.py`, `gateway/src/tools/payments.py`, `catalog.json`, tests

### P2-4: Implement offset/cursor pagination on list endpoints
**Source:** Customer Report M-6, Agent 5/20
**Current state:** 12+ list endpoints support `limit` but not `offset`, `cursor`, or pagination metadata.
**Action:**
- [x] Add `offset` parameter to list_* tools (list_api_keys, list_webhooks, list_subscriptions, search_services, search_agents, get_events, get_messages, list_disputes, etc.)
- [x] Return pagination metadata: `{"items": [...], "total": N, "offset": M, "limit": L}`
- [x] Add tests for pagination
**Files:** Multiple tool files, storage layers, tests

### P2-5: Fix cross-tenant audit log exposure
**Source:** Customer Report S-10 (CVSS 7.5)
**Current state:** `get_global_audit_log` exposes all operations to any pro agent.
**Action:**
- [x] Require admin scope for global audit log
- [x] Add `get_audit_log(agent_id)` that filters to caller's own operations
- [x] Add tests
**Files:** `gateway/src/tools/paywall.py`, tests

### P2-6: Implement API key TTL/expiration enforcement
**Source:** Customer Report M-7, Agent 23
**Current state:** Key scoping was added (Session TODO Items P1-7) with expiration field, but need to verify enforcement on every request.
**Action:**
- [x] Verify key expiration is checked in auth middleware
- [x] Add test: expired key returns 401
- [x] Add `expires_at` to key creation if not present
**Files:** `gateway/src/middleware.py` or `authorization.py`, tests

### P2-7: Self-service onboarding (bootstrap path)
**Source:** Round 3/4 (MediBot, HireBot, PetCare), Customer Report strategic
**Current state:** `create_api_key` requires auth (chicken-and-egg). x402 facilitator unreliable.
**Action:**
- [x] Add `POST /v1/register` endpoint: accepts no auth, creates free-tier key + wallet with signup bonus
- [x] Rate-limit registration (e.g., 5/hour per IP)
- [x] Add tests
**Files:** `gateway/src/routes/register.py` (new), `gateway/src/app.py`, tests

### P2-8: Add `register_server` to trust service
**Source:** Customer Report C-8 (incomplete CRUD lifecycle)
**Action:**
- [x] Add `register_server` tool to trust service
- [x] Register in catalog.json
- [x] Add tests
**Files:** `products/trust/src/api.py`, `gateway/src/tools/trust.py`, `catalog.json`, tests

---

## P3 -- Developer Experience & API Quality

### P3-1: Fix OpenAPI ErrorResponse schema to match live API
**Source:** Customer Report H-10, Agent 19/20
**Current state:** OpenAPI says `{"error": "string", "detail": "string"}`, live returns `{"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}`.
**Action:**
- [x] Update ErrorResponse schema in OpenAPI generator to match actual format
- [x] Add tests
**Files:** `gateway/src/openapi.py`, tests

### P3-2: Add CORS middleware
**Source:** Round 4 (SecurityBot), Customer Report P1-4
**Action:**
- [x] Add CORS middleware with configurable allowed origins
- [x] Add Strict-Transport-Security, X-Frame-Options, X-Content-Type-Options headers
- [x] Add tests
**Files:** `gateway/src/middleware.py`, tests

### P3-3: Add security headers middleware
**Source:** Round 4 (SecurityBot P1-5)
**Action:**
- [x] Add `X-Content-Type-Options: nosniff`
- [x] Add `X-Frame-Options: DENY`
- [x] Add `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- [x] Add `Content-Security-Policy: default-src 'none'`
- [x] Add tests verifying headers present
**Files:** `gateway/src/middleware.py`, tests

### P3-4: Truncate/sanitize tool name in error messages
**Source:** Round 4 (SecurityBot P2-1/P2-2)
**Current state:** Oversized/malicious tool names reflected verbatim in error responses (log flooding risk).
**Action:**
- [x] Truncate tool name to 128 chars in error messages
- [x] Strip null bytes from all input params
- [x] Add tests
**Files:** `gateway/src/routes/execute.py`, tests

### P3-5: Enforce `extra="forbid"` on ExecuteRequest body
**Source:** Round 4 (CodeForge), Customer Report P1-6
**Current state:** Extra fields in request body silently accepted.
**Action:**
- [x] Apply Pydantic model with `extra="forbid"` to execute request parsing
- [x] Add test: extra field returns 422
**Files:** `gateway/src/routes/execute.py`, tests

### P3-6: Fix 413 to return JSON instead of HTML
**Source:** Round 4 (ReadGate, GameDev)
**Current state:** nginx returns raw HTML for 413. Breaks JSON-only clients.
**Action:**
- [x] Add app-level body size check before nginx (e.g., middleware checking Content-Length)
- [x] Return structured JSON: `{"error": {"code": "payload_too_large", "message": "..."}}`
- [x] Add test
**Files:** `gateway/src/middleware.py`, tests

### P3-7: Standardize naming conventions
**Source:** Customer Report M-11, multiple agents
**Current state:** `server_id` vs `agent_id`, 5 different termination verbs, 6 agent reference patterns.
**Action:**
- [x] Map `server_id` -> `agent_id` in trust tools (accept both, prefer `agent_id`)
- [x] Document naming conventions
- [x] Add deprecation aliases where needed
**Files:** `gateway/src/tools/trust.py`, `catalog.json`

---

## P4 -- CI/CD Improvements

### P4-1: Add test coverage reporting to CI (GitHub PR comments + badge)
**Source:** Direct request
**Current state:** Gateway runs `--cov=gateway --cov-fail-under=70` but:
- No coverage report uploaded to GitHub
- Products have no coverage measurement
- No coverage badge or PR comment
**Action:**
- [x] Add `pytest-cov` with `--cov-report=xml` to all test steps (gateway + each product)
- [x] Combine coverage XMLs into a single report
- [x] Add coverage upload step (use `codecov/codecov-action@v4` or similar)
- [x] Add coverage summary as PR comment (use a coverage reporter action)
- [ ] Add `--cov-fail-under=70` to all product test steps (not just gateway)
- [ ] Add coverage badge to README.md
**Files:** `.github/workflows/ci.yml`, `scripts/run_tests.sh`, `README.md`

### P4-2: Add SDK test step to CI
**Source:** MASTER_LOG (SDK tests exist but not in CI)
**Current state:** `sdk` and `sdk-ts` tests are not in the CI pipeline test matrix.
**Action:**
- [x] Add SDK Python test step to CI
- [x] Add SDK TypeScript test step to CI (if node available)
**Files:** `.github/workflows/ci.yml`

---

## P5 -- Strategic & Architecture (Plan Only)

These items should be planned but implementation deferred to dedicated sessions.

### P5-1: Dissolve or expand starter tier
**Source:** Customer Report M-2, Agent 16/17
**Current state:** 6 tools, all in payments, all $0.00/call. Vestigial.
**Decision needed:** Merge into free or expand with escrow/webhooks/disputes.

### P5-2: Decompose pro tier into modular bundles
**Source:** Customer Report strategic
**Current state:** 56 tools spanning 10+ domains. Agent needing GitHub must buy Stripe+Postgres+Admin+Disputes.
**Decision needed:** Growth ($29), Stripe ($19), GitHub ($9), Postgres ($19)?

### P5-3: Populate enterprise tier
**Source:** Customer Report M-3
**Current state:** Present in enum, maps to zero tools. Causes confusion.
**Decision needed:** Admin tools, audit log, SLA compliance, process_due_subscriptions?

### P5-4: Health check all databases
**Source:** Round 3 (health check only probed billing DB while paywall was down)
**Action:** Extend `/v1/health` to probe ALL databases. Already partially done (billing DB probe) but needs paywall, payments, marketplace, trust, identity, messaging.

### P5-5: Document x402 payment proof format
**Source:** Customer Report M-8
**Current state:** 15 words of documentation. No SDK, no testnet, no example payload.

### P5-6: Build `bootstrap_agent` meta-tool
**Source:** Customer Report P3-29
**Action:** Atomic onboarding: register + wallet + key + deposit in one call.

### P5-7: Integrate event_bus schema validation with publish_event
**Source:** Customer Report M-5
**Current state:** Events and event_bus services operate independently. Schemas not enforced on publish.

---

## Implementation Order (for overnight session)

The order below is designed for maximum impact with minimal dependency chains. Items are grouped so that TDD cycles flow naturally.

### Phase 1: Database fixes (unblock broken features)
1. P1-1 (payments migrations)
2. P1-2 (messaging migrations)
3. P1-3 (exchange rate fix)

### Phase 2: Security hardening
4. P0-1 (pg_execute restriction)
5. P0-3 (freeze_wallet tier + admin scope)
6. P0-4 (webhook SSRF)
7. P0-5 (backup key leak + path traversal)
8. P0-6 (key tier escalation)
9. P0-7 (dispute impersonation)
10. P0-2 (ownership validation audit)

### Phase 3: Feature gaps
11. P2-1 (get_budget_cap)
12. P2-5 (audit log access control)
13. P2-7 (self-service registration)
14. P1-4 (idempotency keys)
15. P1-5 (atomic convert_currency)

### Phase 4: DX & API quality
16. P3-5 (extra=forbid on execute)
17. P3-4 (truncate tool names)
18. P3-2 (CORS middleware)
19. P3-3 (security headers)
20. P3-1 (OpenAPI error schema)
21. P3-6 (JSON 413 response)

### Phase 5: CI/CD
22. P4-1 (coverage reporting in CI)
23. P4-2 (SDK tests in CI)

### Phase 6: Remaining features (if time permits)
24. P2-2 (multi-currency in gateway tools)
25. P2-3 (list_intents, list_escrows)
26. P2-4 (pagination)
27. P2-6 (key TTL enforcement)
28. P2-8 (register_server)
29. P3-7 (naming standardization)

---

## Success Criteria

- All P0 security items addressed with tests
- Payments and messaging OperationalErrors resolved
- Exchange rate tool functional
- Coverage shows up in GitHub CI (PR comments or badge)
- All existing tests continue to pass
- No regressions in customer-facing functionality

---

## Reference: Score Trajectory

| Round | Score | Delta | Key Issue |
|-------|-------|-------|-----------|
| Round 1 | 6.9 | -- | Initial baseline |
| Round 2 | 7.4 | +0.5 | Feature improvements |
| Round 3 | 2.7 | -4.7 | Paywall DB outage |
| Round 4 | 6.68 | +3.98 | Recovery, DB bugs persist |
| **Target** | **8.5+** | +1.8 | Fix DB bugs + security + DX |

## Reference: v2 Customer Report Composite Score

| Dimension | Score | Grade |
|-----------|-------|-------|
| Vision | 9.5/10 | A+ |
| Architecture | 6.5/10 | B- |
| Security | 3.0/10 | D |
| Server Performance | 9.0/10 | A |
| Client-Perceived Performance | 4.0/10 | D+ |
| Data Integrity | 6.2/10 | C+ |
| Developer Experience | 5.7/10 | C |
| Tier/Pricing Design | 5.0/10 | C- |
| **Composite** | **5.7/10** | **C+** |

**Target after this session: Security 6.0+ (D -> C+), Data Integrity 7.5+ (C+ -> B), DX 7.0+ (C -> B-)**
