# Green Helix A2A Commerce Platform — Pre-Production Grand Pre-Launch Audit

**Target:** `https://api.greenhelix.net/v1`
**Date:** 2026-04-04
**Server Version:** 0.9.2
**Previous Audit:** v0.9.1 (2026-04-02), v0.5.3 (2026-03-31)
**Auditor:** Autonomous Multi-Persona Test Orchestrator
**Methodology:** 4-phase audit with persona rotation (Naive Developer, Marketing Analyst, Control Agent, Red Team)
**Test Coverage:** ~200 tests across 4 phases, ~400+ HTTP requests
**API Keys:** Self-registered free-tier keys (3 agents)

---

## 1. Executive Summary

### Verdict: **CONDITIONAL GO** — Launch with Remediation Plan

Green Helix v0.9.2 shows meaningful improvement over v0.9.1. Self-registration now works, REST migration is complete (117 endpoint operations across 101 paths), all 3 hosts are in sync, sub-penny amounts are now rejected, and negative/zero deposits correctly return 422. However, **4 issues require attention before production traffic**:

### Top 4 Critical Risks

| # | Risk | Severity | Blocking? |
|---|------|----------|-----------|
| 1 | **Deposit upper bound too permissive (1B credits for free tier)** | CRITICAL | Yes — free agent deposited 999M in one request |
| 2 | **Bimodal DNS latency (~5.1s on 40-60% of requests)** | HIGH | Yes — p95 > 5,200ms |
| 3 | **IPv6 completely non-functional** | HIGH | No — but AAAA records exist, causing Happy Eyeballs penalties |
| 4 | **55% of OpenAPI response schemas are empty** | HIGH | No — but breaks SDK code generation |

### Changes Since v0.9.1 (Previous Audit)

| Issue | v0.9.1 | v0.9.2 |
|-------|--------|--------|
| Self-registration | 400 on test payloads | **FIXED** — `POST /v1/register` works, returns key + 500 credits |
| Sub-penny amounts | Silently rounded | **FIXED** — 422 `Decimal input should have no more than 2 decimal places` |
| Negative/zero amounts | Needs verification | **VERIFIED** — 422 `Input should be greater than 0` |
| Extreme amounts (1e18) | HTTP 500 | **FIXED** — 422 `Input should be less than or equal to 1000000000` |
| test.greenhelix.net | 502 (backend down) | **FIXED** — healthy, v0.9.2, all DBs ok |
| REST migration | 100 endpoints | **117 operations** across 101 paths (execute returns 410 "tool-moved") |
| Rate limiting | 429s at 100/hr | **CONFIRMED** — 429 with counter `"101/100 per hour"` |
| /v1/pricing/tiers | Not found | **NEW** — returns 4 tiers with subscriptions |
| /v1/onboarding | Not found | **NEW** — returns OpenAPI onboarding quickstart |
| /v1/signing-key | Unknown | **Accessible** — returns HMAC-SHA3-256 public key |

### Persistent Issues (Unfixed Since v0.9.1 or Earlier)

| Issue | Status |
|-------|--------|
| Bimodal DNS latency (~5.1s) | Still present |
| X-API-Key undocumented auth path | Still accepted (Bearer takes precedence) |
| Input reflection in BOLA 403 errors | Still present |
| No app-level payload size limit | 1MB accepted |
| No idle connection timeout | Still present |
| Slowloris (LV-01/LV-02) | Not retested (requires pro-tier + long connections) |

---

## 2. Vulnerability Log

### CRITICAL

#### C-1: Deposit Upper Bound Dangerously Permissive (NEW)

**Reproduction:**
```bash
curl -s -X POST \
  -H "Authorization: Bearer $FREE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": 999999999, "currency": "CREDITS"}' \
  https://api.greenhelix.net/v1/billing/wallets/audit-retest-free/deposit
# Returns 200, new_balance: "1000000509.00"
```

**Impact:** A free-tier agent can deposit 999,999,999 credits ($10M at 100:1 exchange rate) in a single request. The max validation of 1,000,000,000 applies uniformly across all tiers. This enables:
- Artificial balance inflation
- Potential payment fraud if deposits map to real currency
- Leaderboard manipulation (agent immediately enters top 10)

**Remediation:** Add per-tier deposit limits: free=1,000, starter=10,000, pro=100,000, enterprise=configurable. Add per-period cumulative caps.

### HIGH

#### H-1: Bimodal DNS Latency — ~5.1s Penalty (Persistent)

**v0.9.2 Data (80 requests across all configurations):**

| Configuration | Slow % | Fast avg | Slow avg | Note |
|---------------|--------|----------|----------|------|
| Default (dual-stack) | 60% | 270ms | 5,250ms | Worst case |
| IPv4-only (`--ipv4`) | 40% | 208ms | 5,224ms | 20% improvement |
| IPv6-only (`--ipv6`) | 50% | 75ms* | 5,053ms* | *All TCP connections fail (exit 7) |
| Keep-alive | 0%** | 79ms | N/A | **After initial connection |
| Sandbox | 55% | 275ms | 5,281ms | Same pattern = shared infra |

**Key finding:** Keep-alive connections average **79ms** with max 88ms across 19 subsequent requests. The DNS penalty is 100% eliminated by connection reuse.

**Percentiles (20 default requests):** p50=5,243ms, p90=5,260ms, p95=5,263ms

**Root Cause:** Unchanged from v0.9.1. DNS cache TTL on Cloudflare resolver causes ~5s timeout on cache miss. Affects all hosts equally.

#### H-2: IPv6 Completely Non-Functional (NEW)

DNS returns AAAA records for `api.greenhelix.net`, but TCP connections always fail (curl exit code 7, `time_connect=0.000000`). All 20 IPv6 attempts failed.

**Impact:** IPv6-only clients cannot reach the API. Worse, clients using Happy Eyeballs (most modern HTTP stacks) will attempt IPv6 first, fail, then fall back to IPv4 — adding latency.

**Remediation:** Either configure IPv6 on Cloudflare/origin or remove AAAA DNS records.

#### H-3: 55% of OpenAPI Response Schemas Empty (NEW)

55% of endpoint response schemas are `schema: {}` — no type information. This breaks SDK code generation (clients get `Any` or `object` return types) and makes the API spec incomplete despite having 100% endpoint coverage.

**Remediation:** Add response schemas to all endpoints. At minimum: balance, transactions, services, agents, escrows, intents.

#### H-4: X-API-Key Undocumented Auth Path (Persistent)

Still accepted in v0.9.2. When both headers present, `Authorization: Bearer` takes precedence consistently. Documented in `/v1/onboarding` spec but not in main OpenAPI `securitySchemes`.

### MEDIUM

#### M-1: Financial Values Returned as Strings (NEW)

`balance` and `new_balance` are returned as strings (`"505.00"`) instead of JSON numbers. But `/v1/register` returns `balance` as number (`500.0`). Inconsistent serialization forces consumers to handle both types.

**Remediation:** Pick one representation. If strings for decimal precision, document it. If numbers, be consistent.

#### M-2: Input Reflection in BOLA 403 Errors (Persistent)

BOLA 403 responses still echo attacker-supplied `agent_id` verbatim. Now mitigated by CSP (`default-src 'none'`) and `X-Content-Type-Options: nosniff`, but still leaks authenticated agent_id and aids reconnaissance.

#### M-3: No Max-Length on agent_id Path Parameter (NEW)

1000-character agent_id accepted in URL path without rejection. The full value appears in error response `instance` field — potential log injection vector.

**Remediation:** Add path parameter length validation (max 128 chars).

#### M-4: Leaderboard Exposes Test/Perf Agent Data

`GET /v1/billing/leaderboard` returns agents like `perf-agent-1775185745-000` with 190M balance and `cf4-gamedev-ai` with 400M. Leaks internal testing data in production.

**Remediation:** Exclude test/perf agents from leaderboard or use separate environments.

#### M-5: /v1/pricing References Stale Execute-Style Schemas

The pricing endpoint still returns tool schemas referencing the old `/execute` dispatch pattern despite complete REST migration. Confusing for new users.

#### M-6: Identity Agent Lookup Returns 200 for Non-Existent Agents

`GET /v1/identity/agents/{id}` returns `200 OK` with `{found: false}` instead of `404 Not Found`. Violates REST convention and enables existence enumeration.

### LOW

#### L-1: Free Tier Can Create Unlimited Same-Tier API Keys (NEW)

`POST /v1/infra/keys` allows free-tier users to create additional free-tier API keys without limit. Potential rate-limit evasion vector (rotate keys to reset per-key counters).

#### L-2: Key Rotation Endpoint Reveals Field Names Before Auth Check

`POST /v1/infra/keys/rotate` returns 422 with validation errors exposing required field names before checking authorization — information disclosure.

#### L-3: Billing Estimate Ignores Unknown Parameters

`GET /v1/billing/estimate?tool_name=best_match&num_calls=10` silently ignores `num_calls` (correct param is `quantity`). No warning returned.

#### L-4: Onboarding Spec Version Mismatch

`/v1/onboarding` returns OpenAPI spec with `version: "0.1.0"` while main spec reports `0.9.2`. Stale spec confuses automated tooling.

#### L-5: Inconsistent Pagination

Some list endpoints return `{items: [], count: 0}`, others return just `{items: []}` or `{services: []}`. No `cursor`, `next`, or `has_more` fields.

---

## 3. Performance Analytics: The 5.2s DNS Anomaly

### v0.9.2 Update

The bimodal latency is **unchanged from v0.9.1**. All hosts (api, sandbox, test) exhibit the same pattern, confirming shared Cloudflare infrastructure as root cause.

**New finding: IPv6 is broken.** AAAA records resolve but TCP connections fail. This worsens the latency issue for dual-stack clients using Happy Eyeballs:

```
Happy Eyeballs flow:
1. Resolve AAAA + A (both succeed)
2. Attempt IPv6 TCP connection → FAIL
3. Fall back to IPv4 → success (but +5.1s if DNS cache cold)
Total worst case: 5.1s (DNS) + timeout (IPv6) + 5.1s (DNS again?) = potentially >10s
```

### Sustained Load Profile (100 requests, v0.9.2)

```
Batch  1-20:  avg 2,511ms  errors 0/20
Batch 21-40:  avg 1,502ms  errors 0/20
Batch 41-60:  avg 2,019ms  errors 0/20
Batch 61-80:  avg 1,932ms  errors 0/20
Batch 81-100: avg 1,989ms  errors 0/20

Percentiles: p50=274ms  p90=5,259ms  p95=5,270ms
Trend: Stable (no degradation)
Error rate: 0%
```

### Keep-Alive Performance (Key Recommendation)

| Request | Latency |
|---------|---------|
| 1st (cold) | 264ms |
| 2nd-20th (warm) | **79ms avg** (min 68ms, max 88ms) |

**SDK/client MUST use connection pooling.** This is the single most impactful performance recommendation.

---

## 4. Marketing & Strategy: DX Critique

### Time to Value (v0.9.2 — Improved)

| Milestone | v0.9.1 | v0.9.2 | Change |
|-----------|--------|--------|--------|
| Find docs | ~0s | ~0s | Same |
| Self-register | **BROKEN** (400) | **10 seconds** | MAJOR FIX |
| First API call | ~280ms | ~264ms | Same |
| First auth call | ~5.2s | ~5.2s | Same (DNS) |
| Browse pricing | No tiers endpoint | `/v1/pricing/tiers` works | NEW |

### What v0.9.2 Gets Right

1. **Self-registration works.** `POST /v1/register {"agent_id":"my-agent"}` → key + wallet + 500 credits. One-step onboarding. This was the #1 DX blocker in v0.9.1 and it's fixed.

2. **Full REST migration.** 117 endpoint operations. The `410 Gone` response for old `/execute` tools includes migration guidance. Clean transition.

3. **Tier transparency.** `/v1/pricing/tiers` returns 4 tiers with rate limits, burst allowances, support levels, subscription prices, and credit allocations. This was missing in v0.9.1.

4. **Genuinely A2A-native primitives.** Performance-gated escrows, Merkle claim chains for verifiable attestation, agent reputation scoring, multi-currency wallets (BTC/ETH/CREDITS/USD). Not a wrapped human API.

5. **Security posture.** All injection tests negative, BOLA enforced, race conditions solved, rate limiting enforced, comprehensive security headers.

### What Still Needs Work

1. **Empty marketplace.** Zero services, zero registered agents (besides test accounts). The API infrastructure is ready but the network effect is zero. Seed with reference services.

2. **55% empty response schemas.** Breaks SDK codegen. The OpenAPI spec has 100% endpoint coverage but the response types are mostly `schema: {}`.

3. **No SDKs.** Python and TypeScript SDKs should be generated from the OpenAPI spec. Connection pooling (critical for DNS latency) should be default.

4. **Financial type inconsistency.** Balance as string in REST, number in register. Pick one.

5. **No CORS.** Browser-based agent dashboards or integrations are blocked.

### Market Positioning

**Position as "Stripe for AI Agents."** The A2A-native primitives (escrow, reputation, claim chains, multi-agent wallets) are genuinely differentiated. De-emphasize generic tools (GitHub, Postgres, Stripe webhook) that dilute the narrative. The empty marketplace is the #1 commercial risk — seed it before launch.

### DX Score: **7/10** (up from 6/10)
Self-registration and pricing tiers improved the onboarding significantly. Empty schemas and no SDKs prevent a higher score.

---

## 5. Actionable Todo List: 30/60/90 Day Roadmap

### 30 Days (Pre-Launch Blockers)

- [ ] **Add per-tier deposit limits** — Free tier should not accept 999M deposits. Implement: free=1K, starter=10K, pro=100K.
- [ ] **Fix DNS latency** — Investigate Cloudflare DNS TTL. Remove AAAA records if IPv6 isn't supported. Target: p95 < 500ms.
- [ ] **Add response schemas to OpenAPI** — Fill in the 55% empty `schema: {}` entries. Critical for SDK generation.
- [ ] **Document or disable X-API-Key auth** — Add to OpenAPI `securitySchemes` or remove the middleware.
- [ ] **Fix financial type inconsistency** — Return balance as same type everywhere (string or number, not both).
- [ ] **Sanitize BOLA error messages** — Don't echo raw agent_id input in 403 detail.
- [ ] **Fix identity agent 404** — Return 404 for non-existent agents, not `200 {found: false}`.
- [ ] **Clean leaderboard data** — Exclude test/perf agents from production leaderboard.

### 60 Days (Post-Launch Hardening)

- [ ] **Generate Python + TypeScript SDKs** — Use OpenAPI spec. Default to connection pooling.
- [ ] **Seed marketplace** — Register 10+ reference services to demonstrate the platform.
- [ ] **Add agent_id path length validation** — Max 128 chars, sanitize in error responses.
- [ ] **Rate-limit API key creation** — Prevent unlimited free key generation.
- [ ] **Update /v1/pricing schemas** — Remove stale `/execute` references, align with REST endpoints.
- [ ] **Fix onboarding spec version** — Match `/v1/onboarding` version to main spec.
- [ ] **Add pagination** — `cursor`, `has_more`, `total` on all list endpoints.
- [ ] **Add CORS policy** — Support OPTIONS with configurable origins.
- [ ] **Add app-level body size limit** — 64KB at application layer.
- [ ] **Enforce rate limits consistently** — Counter decrements but enforcement appears inconsistent across endpoints.

### 90 Days (Market Readiness)

- [ ] **Connection pooling documentation** — SDK guide with keep-alive best practices.
- [ ] **Status page** — Public uptime monitoring.
- [ ] **Sandbox documentation** — Document sandbox.greenhelix.net for testing.
- [ ] **Changelog/versioning** — Public changelog, breaking change notifications.
- [ ] **Slowloris protection** — Header/body timeouts (LV-01/LV-02 from v0.5.3 audit).
- [ ] **Idle connection timeout** — Set keepalive_timeout to 60-120s.
- [ ] **Request signing** — HMAC-SHA3-256 signing key endpoint exists but no documentation on usage.
- [ ] **Idempotency keys** — Implement for all mutating financial endpoints.

---

## 6. Pre-Launch Readiness Score

| Category | v0.9.1 | v0.9.2 | Weight | Weighted |
|----------|--------|--------|--------|----------|
| **Security** | 8/10 | **8/10** | 25% | 2.00 |
| **Reliability** | 6/10 | **7/10** | 25% | 1.75 |
| **Functionality** | 8/10 | **8/10** | 20% | 1.60 |
| **Performance** | 5/10 | **5/10** | 15% | 0.75 |
| **Developer Experience** | 6/10 | **7/10** | 15% | 1.05 |
| **TOTAL** | **6.75** | | 100% | **7.15/10** |

### Category Breakdown

**Security (8/10):** BOLA enforced on all cross-agent tests. All injection tests negative. Race conditions solved (5 and 10 concurrent deposits both correct). Rate limiting enforced. Deducted for: deposit limits too permissive (new CRITICAL), X-API-Key undocumented, input reflection, unlimited key creation.

**Reliability (7/10):** 100% success rate on 100 sustained-load requests. Zero errors. Clean recovery after malformed requests. All 3 hosts healthy and in sync. Deducted for: bimodal latency kills SLA metrics, rate limit enforcement appears inconsistent.

**Functionality (8/10):** 117 endpoint operations across 101 paths. Full REST migration. Self-registration works. Pricing tiers endpoint new. Deducted for: empty marketplace, no pagination, empty response schemas.

**Performance (5/10):** Fast-path is excellent (264ms cold, 79ms warm). But p95 at 5,270ms and IPv6 completely broken. Keep-alive mitigates but requires client implementation.

**Developer Experience (7/10):** Self-registration works (major improvement). Swagger UI, onboarding endpoint, tier documentation all new. Deducted for: 55% empty response schemas, no SDKs, financial type inconsistency, stale pricing schemas.

---

## Appendix A: Test Coverage by Phase

| Phase | Persona | Focus | Key Findings |
|-------|---------|-------|-------------|
| 0 | Naive Developer | Onboarding | Registration works (7/10). Onboarding spec stale. |
| 1 | Marketing Analyst | DX Critique | 55% empty schemas. Financial type inconsistency. Empty marketplace. |
| 2 | Control Agent | Network & Boundaries | DNS bimodal confirmed. IPv6 broken. Deposit limits too high. Sub-penny fixed. |
| 3 | Red Team | Adversarial | All BOLA/BFLA/injection/race tests pass. Unlimited key creation (low). |
| 4 | Control Agent | Stability | 100% availability. 8/10 stability. All hosts in sync. |

## Appendix B: Improvements Across 3 Audit Rounds

| Version | Date | Endpoints | Key Fix |
|---------|------|-----------|---------|
| v0.5.3 | 2026-03-31 | 6 (128 tools via /execute) | Security headers added |
| v0.9.1 | 2026-04-02 | 100 REST + /execute | Race conditions fixed, escrow BOLA fixed, rate limiting |
| v0.9.2 | 2026-04-04 | 117 ops / 101 paths | Registration, sub-penny validation, test host recovered |

## Appendix C: Finding Severity Totals

| Severity | Count | IDs |
|----------|-------|-----|
| CRITICAL | 1 | C-1 (deposit limits) |
| HIGH | 4 | H-1 (DNS), H-2 (IPv6), H-3 (empty schemas), H-4 (X-API-Key) |
| MEDIUM | 6 | M-1 through M-6 |
| LOW | 5 | L-1 through L-5 |
| **Total** | **16** | |

---

*Report generated 2026-04-04 — Green Helix Pre-Launch Audit Framework v0.9.2*
*Raw data: `security_tests/results/prelaunch_v092_p{0_p1,2_network,3_adversarial,4_stability}.json`*
*Previous reports: v0.9.1 (2026-04-02), v0.5.3 (2026-03-31)*
