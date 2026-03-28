# A2A Commerce Platform — Architecture Review

**Date:** 2026-03-28 | **Version:** 0.2.0 | **Reviewer:** Software Architect (automated)

---

## Executive Summary

The A2A Commerce Platform is a well-structured Starlette-based ASGI gateway with 14 product modules, an SDK, and comprehensive CI/CD. The codebase has solid foundations — clean async patterns, modular product isolation, and 291+ gateway tests — but suffers from **3 critical security issues**, **1 god-object anti-pattern**, **massive storage layer duplication**, and **missing interface contracts**. Estimated remediation: 2-3 weeks for critical/high items.

**Maturity: 5.5/10** — Functional but needs hardening before scaling.

---

## 1. Security (CRITICAL)

### SEC-1: Rate limit bypass via silent exception (execute.py:162)
```python
except Exception: pass  # If rate counting fails, allow the request
```
An exception in the rate-limit lookup **silently allows the request through**. An attacker could trigger this to bypass all rate limits. Same pattern at line 217 silently drops usage/billing records.

**Fix:** Log and return 503, never fail-open on rate limiting.

### SEC-2: Batch endpoint skips per-tool rate limits (batch.py)
The `/v1/batch` endpoint does NOT enforce per-tool rate limits. An attacker can batch 10 calls to a rate-limited tool in one request, bypassing the hourly cap entirely. The single-call endpoint (`execute.py:146-161`) has this check; batch does not.

**Fix:** Apply the same `get_tool_rate_count()` check inside the batch loop.

### SEC-3: SQL construction in `_get_metrics_timeseries` (tools.py:1075-1117)
The `interval` parameter controls an `if/else` that selects a `bucket_expr` string, which is then interpolated into an f-string SQL query. While the current if/else prevents arbitrary injection, the pattern is fragile — any refactor that adds new intervals or changes the branching could introduce SQL injection.

**Fix:** Add explicit whitelist: `if interval not in ("hour", "day"): raise ValueError(...)`.

### SEC-4: API keys accepted via query parameter (auth.py:27-29)
Query parameters are logged in server access logs, proxy logs, browser history, and Referer headers. This leaks credentials.

**Fix:** Deprecate query param auth. Accept only `Authorization: Bearer` and `X-API-Key` headers.

### SEC-5: Stripe webhook signature optional (stripe_checkout.py)
If `STRIPE_WEBHOOK_SECRET` is not set, signature validation is skipped entirely. Any payload is accepted and credited to the agent.

**Fix:** Refuse webhooks when secret is not configured.

---

## 2. Architecture

### ARCH-1: God object — `tools.py` (1,872 lines, 72 tools)
All tool implementations live in a single file. Impossible to test in isolation, high cognitive load, merge conflicts guaranteed.

**Fix:** Split into `gateway/src/tools/{billing,payments,marketplace,trust,identity,system}.py` with a `__init__.py` re-exporting `TOOL_REGISTRY`.

### ARCH-2: No interface contracts between gateway and products
Product dependencies are typed as `Any`:
```python
PaymentEngine.wallet: Any  # billing Wallet
PaywallMiddleware.tracker: Any  # UsageTracker
Marketplace.trust_provider: Any | None = None
```
If a product module changes its API, the gateway breaks silently at runtime.

**Fix:** Define `typing.Protocol` classes in `gateway/src/contracts.py` for each product interface (BillingBackend, PaymentBackend, etc.).

### ARCH-3: Storage layer duplicated 8x (~800 LOC)
Every product module reimplements identical boilerplate: DSN parsing, `connect()/close()`, `row_factory` setup, `harden_connection` import with try/except fallback, schema-as-string-constant.

**Fix:** Extract `BaseStorage` in `products/shared/src/base_storage.py`. All 8 storage classes inherit from it.

### ARCH-4: DSN parsing duplicated 7x
```python
dsn.replace("sqlite:///", "")  # copy-pasted in 7 modules
```
**Fix:** Single `parse_sqlite_dsn()` utility in `shared`.

### ARCH-5: Dual error hierarchies with name collision
- `shared.errors.AuthenticationError` vs `paywall.middleware.AuthenticationError` — same name, different classes.
- Module-specific bases (`PaymentError`, `PaywallError`) prevent unified exception handling in gateway.

**Fix:** Rename paywall's to `PaywallAuthError`. Consider a unified base exception with `retryable` flag.

### ARCH-6: Shared module has dead code
- `shared/src/rate_limiter.py` — token bucket implementation, **never imported** by any module (paywall reimplements in SQL).
- `shared/src/retry.py` — HTTP retry logic, **never imported**.
- `shared/src/audit_log.py` — minimal adoption.

**Fix:** Either adopt or delete. Dead code misleads contributors.

---

## 3. Performance

### PERF-1: N+1 queries in batch endpoint
For each of N calls in a batch: 1 key validation + 1 rate check + 1 tool-rate check + 1 usage record = 4 queries. 10-call batch = 40 queries.

**Fix:** Batch-fetch rate counts for all tools upfront: `get_batch_tool_counts(agent_id, tool_names)`.

### PERF-2: Sliding window rate limit scans full table
`get_sliding_window_count()` scans all rate events for the last hour on every request. At scale this is O(n) per request.

**Fix:** Time-bucket aggregation (hourly counters) instead of per-event scanning.

### PERF-3: Dockerfile runs 2 workers with SQLite
SQLite supports only 1 concurrent writer. 2 uvicorn workers will contend on DB locks.

**Fix:** Single worker for SQLite mode, or document PostgreSQL requirement for multi-worker.

---

## 4. Maintainability & Technical Debt

### DEBT-1: Hardcoded configuration values throughout
| Location | Value | Impact |
|----------|-------|--------|
| `identity/src/api.py:42` | Attestation TTL = 7 days | Can't tune per environment |
| `identity/src/api.py:375-378` | Reputation source weights (100, 70, 40) | Can't A/B test |
| `identity/src/api.py:392-396` | Reputation component weights (0.4, 0.3, 0.3) | Can't tune |
| `marketplace/src/marketplace.py:345-354` | Ranking score components & thresholds | Frozen behavior |
| `routes/batch.py:23` | `_MAX_BATCH_SIZE = 10` | Can't configure per tier |

**Fix:** Extract to config dataclass per module, accept as init parameter, default from env vars.

### DEBT-2: Inconsistent import styles across products
- Billing: relative imports (`.storage`)
- Payments: absolute (`payments.models`) AND wrong-level (`from src.wallet`)
- Reputation: full path (`products.trust.src.scorer`)

**Fix:** Standardize on one pattern (recommend: relative within module, absolute cross-module).

### DEBT-3: Empty `__init__.py` in messaging and payments
These modules force consumers to import from internal paths (`from payments.src.engine import ...`).

**Fix:** Export public API from `__init__.py`.

### DEBT-4: 18 TODOs in identity module
All are P0-P3 customer feedback items (commitment reveals, attestation revocation, pagination, W3C VC alignment). These represent planned work, not tech debt, but should be tracked in an issue tracker.

### DEBT-5: No schema versioning / migration story
All 8 storage modules define schema as string constants. No way to evolve schema without manual migration. Adding a column requires coordinating across module + gateway.

**Fix:** Add `schema_version` table and migration runner in `BaseStorage`.

---

## 5. Scalability

### SCALE-1: SQLite ceiling
SQLite is embedded, single-writer. The gateway already has `db.py` with PostgreSQL DSN parsing, but no product modules support PostgreSQL natively.

**Fix:** Ensure `BaseStorage` (ARCH-3) abstracts the connection backend. Products should work with both SQLite and PostgreSQL via DSN config.

### SCALE-2: No connection pooling for SQLite
`aiosqlite` doesn't pool. Each storage class opens one connection. Under load, this bottlenecks.

**Fix:** For SQLite, this is inherent. Document that PostgreSQL is required for >50 req/s sustained.

### SCALE-3: Webhook delivery not durable
If gateway crashes between event publish and webhook delivery, the event is lost.

**Fix:** Transactional outbox pattern — enqueue delivery in the same DB transaction as event creation.

---

## 6. Interface Definitions

### IF-1: Gateway → Product interface is implicit
No contracts. Breakage discovered only at runtime.

*See ARCH-2 above.*

### IF-2: SDK ↔ Gateway drift risk
SDK has no streaming support (SSE). No batch execution helper. No `A2A_API_KEY` env var auto-loading. SDK trusts API responses without validation (`resp.json()["tools"]` crashes if key missing).

**Fix priority:**
1. Add response validation (`.get()` with defaults)
2. Add `batch_execute()` method
3. Add env var fallback for API key
4. Add SSE streaming support

### IF-3: Rate limiting implemented 3 different ways
- `shared/src/rate_limiter.py`: Token bucket (unused)
- `paywall/src/middleware.py`: SQL-based sliding window
- `billing/src/policies.py`: Simple dict counter

**Fix:** Pick one. Adopt `shared/rate_limiter.py` or delete it.

---

## 7. CI/CD Gaps

### CI-1: No linting or type checking
No ruff, mypy, or bandit in CI. Type errors and style issues caught only in review.

**Fix:** Add `ruff check .` and `mypy gateway/ products/ sdk/` steps to `ci.yml`.

### CI-2: No dependency scanning
No `pip-audit`, `safety`, or lock file. Reproducibility not guaranteed.

**Fix:** Generate and commit a lock file. Add `pip-audit` to CI.

### CI-3: `.gitignore` too sparse (12 lines)
Missing: `.vscode/`, `.idea/`, `*.swp`, `.DS_Store`, `dist/`, `build/`, `*.db`, `*.log`, `*.key`, `*.pem`, `venv/`, `tmp/`.

**Fix:** Expand `.gitignore` to cover IDE, OS, build, data, and secret patterns.

---

## Prioritized Action Items

### P0 — Critical (fix before any production traffic)

| # | Item | Effort | Files |
|---|------|--------|-------|
| 1 | SEC-1: Replace `except Exception: pass` in rate limiting with 503 response | 1h | `execute.py` |
| 2 | SEC-2: Add per-tool rate limit enforcement in batch endpoint | 2h | `batch.py` |
| 3 | SEC-3: Whitelist `interval` param in metrics timeseries | 30m | `tools.py` |
| 4 | SEC-5: Refuse Stripe webhooks when secret not configured | 30m | `stripe_checkout.py` |

### P1 — High (this sprint)

| # | Item | Effort | Files |
|---|------|--------|-------|
| 5 | ARCH-1: Split `tools.py` into 6 module files | 4h | `gateway/src/tools/` |
| 6 | ARCH-3: Extract `BaseStorage` class | 4h | `shared/`, 8 storage files |
| 7 | ARCH-5: Fix `AuthenticationError` name collision | 1h | `paywall/`, `shared/` |
| 8 | SEC-4: Deprecate query param auth | 1h | `auth.py` |
| 9 | CI-1: Add ruff + mypy to CI | 2h | `ci.yml` |
| 10 | DEBT-3: Export public API from empty `__init__.py` | 1h | `messaging/`, `payments/` |

### P2 — Medium (this quarter)

| # | Item | Effort | Files |
|---|------|--------|-------|
| 11 | ARCH-2: Define Protocol contracts for product interfaces | 4h | `gateway/src/contracts.py` |
| 12 | DEBT-1: Extract hardcoded config to dataclasses | 6h | identity, marketplace, paywall |
| 13 | PERF-1: Batch rate-limit queries in batch endpoint | 3h | `batch.py`, paywall storage |
| 14 | ARCH-6: Delete dead code in shared (rate_limiter, retry) | 1h | `shared/src/` |
| 15 | DEBT-5: Add schema versioning | 8h | `shared/`, all storage |
| 16 | IF-2: SDK response validation + batch helper | 4h | `sdk/src/` |
| 17 | CI-3: Expand `.gitignore` | 30m | `.gitignore` |

### P3 — Low (backlog)

| # | Item | Effort | Files |
|---|------|--------|-------|
| 18 | PERF-2: Time-bucket rate limiting | 6h | paywall storage |
| 19 | SCALE-3: Durable webhook outbox | 8h | `webhooks.py` |
| 20 | DEBT-2: Standardize import styles | 3h | all product modules |
| 21 | IF-3: Consolidate rate limiting implementations | 3h | shared, paywall, billing |
| 22 | CI-2: Add dependency lock file + pip-audit | 2h | CI, pyproject files |
| 23 | IF-2 (cont): SDK streaming + env var support | 4h | `sdk/src/` |

---

## Scorecard

| Dimension | Score | Notes |
|-----------|-------|-------|
| Security | 4/10 | Silent fail-open, missing batch rate limits, query param auth |
| Architecture | 6/10 | Clean async, good product isolation, but god-object + no contracts |
| Performance | 6/10 | Fine for current load; N+1 queries and table scans at scale |
| Maintainability | 5/10 | 800 LOC duplication, hardcoded config, inconsistent patterns |
| Scalability | 5/10 | SQLite ceiling, no connection pooling, no durable delivery |
| Interface quality | 5/10 | Implicit contracts, SDK drift, 3 rate-limit implementations |
| Test coverage | 7/10 | 291 gateway tests, but SDK sparse and no integration tests |
| CI/CD | 7/10 | Good pipeline, missing linting/security/lock files |
| **Overall** | **5.5/10** | Functional; needs hardening for production scale |
