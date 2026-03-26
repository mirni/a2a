# Next Steps & Future Improvements

Prioritised roadmap for hardening and extending the A2A commerce platform. Organised into tiers by impact and urgency.

---

## Tier 0 — Critical Correctness ~~(fix before any production traffic)~~ DONE

> All Tier 0 items have been fixed and tested.

### ~~1. Atomic wallet balance operations~~ DONE
Uses atomic `UPDATE ... SET balance = balance - ? WHERE balance >= ?` — concurrent withdrawals can never produce negative balances. 4 new tests including concurrent withdrawal/charge/deposit.

### ~~2. Silent charge failure in paywall middleware~~ DONE
Charge failures now log a warning and write an audit record with `reason=charge_failed:...`. 2 new tests.

### ~~3. Assert statements used as runtime guards~~ DONE
All `assert raw is not None` replaced with explicit `if raw is None: raise RuntimeError(...)`.

### ~~4. Dynamic SQL column names from caller-controlled dicts~~ DONE
`update_subscription` in payments now validates keys against `_SUBSCRIPTION_COLUMNS` allowlist. 3 new tests. (Marketplace and reputation already use explicit named parameters, not dict keys.)

### ~~5. Audit log sanitization~~ DONE
Switched from exact key match to substring matching. Catches `ApiKey`, `stripe_secret_key`, `DB_PASSWORD`, `api_token_v2`, etc. 8 new tests.

---

## Tier 1 — Production Readiness

### ~~6. Marketplace ownership enforcement~~ DONE
`update_service` and `deactivate_service` accept optional `requester_id`. When provided, verifies caller matches `provider_id`. Backwards-compatible (no `requester_id` = no check). 6 new tests.

### ~~7. Marketplace max_cost SQL filter~~ DONE
Moved `max_cost` filter from post-SQL Python filtering into the SQL `WHERE` clause using `json_extract`. No more truncated results at page boundaries. 2 new tests.

### 8. Database migration tooling
All products use `CREATE TABLE IF NOT EXISTS` on every connect. There is no schema versioning, no migration history, and no path for `ALTER TABLE`. Add a lightweight migration framework (version table + ordered SQL scripts per product) or adopt Alembic.

### 9. Health check endpoints for MCP servers
None of the three connectors expose a health endpoint. Container orchestrators (k8s, ECS) cannot determine liveness. Add a `/health` or `ping` tool to each MCP server.

### 10. Graceful shutdown handling
The payments scheduler, reputation pipeline, and MCP servers have no `SIGTERM`/`SIGINT` handlers. SQLite connections are not closed on container termination, risking WAL corruption. Wire `asyncio` signal handlers to each service's `stop()`/`close()` methods.

### 11. Docker and CI/CD
No Dockerfiles for any product. No `docker-compose.yml` for local multi-service development. No GitHub Actions workflow for automated testing. Add:
- Per-product `Dockerfile` (or a single multi-stage build)
- `docker-compose.yml` with all services + persistent volumes
- `.github/workflows/ci.yml` running the full 987-test suite

### 12. Configuration externalisation
Move hardcoded values to environment variables or config files:

| Value | Current location | Suggested config |
|-------|-----------------|------------------|
| Tier definitions (rate limits, costs) | `paywall/src/tiers.py:37-59` | JSON/YAML config file |
| Trust score weights | `trust/src/models.py:72-78` | Environment or config |
| Confidence decay thresholds | `trust/src/scorer.py:22-24` | Environment or config |
| Stripe API version | `connectors/stripe/src/client.py:26` | `STRIPE_API_VERSION` env var |
| Rate limiter defaults | `connectors/stripe/src/client.py:55-58` | Environment variables |
| Subscription month = 30 days | `payments/src/models.py:122` | Calendar-aware calculation |

---

## Tier 2 — Cross-Product Integration

### 11. Wire marketplace to trust scoring
`Marketplace.trust_provider` is optional and defaults to `None`. In production, all `trust_score` fields return `None` and `sort_by=TRUST_SCORE` ranks everything equally. Provide a default adapter that calls `TrustAPI.get_score()` when both products are deployed together.

### 12. Mirror Stripe transactions in internal ledger
The Stripe connector calls Stripe's API in isolation. `create_payment_intent` on Stripe does not create a corresponding `PaymentIntent` in the payments product. Real-money Stripe transactions should be mirrored in the internal ledger for reconciliation.

### 13. Reputation pipeline → marketplace status sync
When the reputation pipeline detects persistent probe failures, there is no mechanism to set the corresponding marketplace service to `SUSPENDED`. The trust score decays, but the service remains `ACTIVE` and appears in search results.

### 14. Cross-product event bus
Each product emits events in isolation. Billing emits `wallet.withdrawal`; payments and reputation emit nothing externally. Add a shared event bus (even a shared SQLite events table as a starting point) for cross-product event consumption. This enables:
- Marketplace suspending services on trust score drop
- Billing webhooks to external systems
- Audit trail across the full transaction lifecycle

### 15. Paywall → billing via public API
The paywall accesses billing internals directly via `self.tracker._storage.record_usage(...)`. This private attribute access breaks if billing's internal layout changes. Use the public `UsageTracker` API or add a dedicated method for external callers.

**File:** `products/paywall/src/middleware.py:278`

---

## Tier 3 — API Completions & Query Gaps

### 16. Pagination for unbounded queries
- `trust/src/storage.py:list_servers()` — returns all servers, no `LIMIT/OFFSET`
- `reputation/src/storage.py:list_targets()` — same issue
- `billing/src/tracker.py:get_usage()` — no `function` filter (must fetch all records to query "calls to tool X in the last hour")

### ~~17. Fix marketplace `max_cost` filtering~~ DONE
Moved into SQL WHERE clause. See Tier 1 item 7.

### 18. Missing CRUD operations
- **Trust:** no `delete_server` or `update_server` — stale servers accumulate indefinitely
- **Marketplace:** no hard delete — `deactivate_service` soft-deletes, but inactive services accumulate forever
- **Payments:** `get_payment_history` excludes subscriptions — agents with only subscription charges see empty history
- **Paywall:** audit log query requires `agent_id` — no admin-level global query

### 19. Input validation gaps
- Stripe connector: `email: str` has no format validation (`products/connectors/stripe/src/models.py:17`)
- Marketplace: `update_service` accepts `status` as raw string, no `ServiceStatus` enum validation (`products/marketplace/src/storage.py:160`)
- Audit log sanitiser only strips exact top-level key matches — misses `ApiKey`, nested keys (`products/shared/src/audit_log.py:73-83`)

---

## Tier 4 — Observability & Testing

### 20. Metrics and structured logging
Zero usage of OpenTelemetry, Prometheus, or structured metrics across all products. Add counters for:
- Wallet transactions per minute
- Payment intent success/failure rates
- Probe latency percentiles
- API key validation pass/fail rates
- Connector tool call counts by tool name

### 21. Cross-product integration tests
The only integration test is `billing/tests/test_integration.py`. Missing test scenarios:
- Marketplace + trust: search with live trust scores
- Paywall + billing: full gate → charge → balance deduction
- Payments + billing: payment capture → wallet credit
- Reputation + trust: probe results → trust score recomputation

### 22. Concurrent wallet operation tests
The race condition (item 1) has no regression test. Add a test that fires N concurrent withdrawals and asserts the final balance is consistent.

### 23. Load and performance tests
No locust, k6, or benchmark tests. The reputation pipeline's `probe_batch` and `scan_batch` run sequentially — they should use `asyncio.gather` with a semaphore for 100+ targets.

### 24. Edge case test coverage
- `best_match` ranking: tied scores, `prefer=LATENCY` with `max_latency_ms=0`, all-free services
- `search` with `max_cost` at page boundary (20 over budget, 5 under, `limit=10`)
- Subscription scheduler: `process_due` exception handling, `asyncio.CancelledError` termination
- Paywall: both `api_key_param` and `agent_id_param` code paths need equivalent coverage

---

## Tier 5 — Feature Extensions (V2)

### 25. Real CVE scanning
`ScanWorker.cve_count` is hardcoded to 0. The trust scorer deducts up to 20 points for CVEs but this path can never fire. Integrate with a vulnerability database (OSV, NVD) to provide real CVE counts for server dependencies.

### 26. Webhook delivery for billing events
`BillingEventStream` stores events and supports push handlers, but there is no HTTP webhook dispatcher with retry-on-failure. External billing systems cannot receive these events.

### 27. Multi-currency and exchange rates
All pricing is in "credits" with no exchange rate to real currency. Add currency abstraction and exchange rate lookup for agents transacting across different payment systems.

### 28. Service-level agreement enforcement
SLA fields (`uptime`, `max_latency_ms`) are stored but never enforced. Wire probe results to SLA checks: if a provider's actual uptime drops below their claimed SLA, automatically flag the service or trigger a refund workflow.

### 29. Agent authentication and identity
No agent authentication system exists. Agents are identified by string IDs with no verification. Add:
- Agent registration with cryptographic identity (public key)
- Signed requests between agents
- Agent capability declarations (what an agent can do, verified by the platform)

### 30. Rate limiting at the platform level
The paywall has per-tier rate limits, but there is no platform-wide rate limiter to prevent a single agent from overwhelming the system. Add a global rate limiter with configurable per-agent and per-IP limits.

---

## Implementation Priority

| Priority | Items | Rationale |
|----------|-------|-----------|
| **Now** | 1-4 | Correctness bugs that cause data loss or security issues |
| **Before first users** | 5-10 | Production infrastructure and safety guardrails |
| **Before scaling** | 11-15 | Cross-product wiring that makes the platform coherent |
| **Ongoing** | 16-24 | API polish, observability, test hardening |
| **V2 roadmap** | 25-30 | Feature extensions that expand the platform's value |
