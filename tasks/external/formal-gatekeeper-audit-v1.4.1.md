# Formal Gatekeeper Audit — v1.4.1

**Date:** 2026-04-13
**Source:** `reports/external/v1.4.1/formal-gatekeeper-audit.md`
**Verdict:** 85% accurate — local code functional, API integration broken
**Tests:** 124/124 pass (local), all API calls fail with 410

---

## Summary

The formal gatekeeper guide (`seed-products/formal-gatekeeper.md`) was
independently audited against the live API. All local code (invariant engine,
plan parser, proof cache, etc.) is functionally correct. API integration is
100% broken because the guide still uses `POST /v1/execute` which was removed.

---

## Findings

### P0 — API endpoint migration (guide file)

**Impact:** Every API call in the guide fails with HTTP 410 Gone.

The guide uses `call_tool("verify_logic", ...)` via `POST /v1/execute`.
This endpoint was removed. All calls must migrate to dedicated REST endpoints:

| Guide call | Actual endpoint |
|-----------|----------------|
| `call_tool("verify_logic", ...)` | `POST /v1/gatekeeper/jobs` |
| `call_tool("verify_logic_z3", ...)` | `POST /v1/gatekeeper/jobs` |
| `call_tool("register_service", ...)` | `POST /v1/marketplace/services` |
| `call_tool("search_services", ...)` | `GET /v1/marketplace/services` |
| `call_tool("create_payment_intent", ...)` | `POST /v1/payments/intents` |
| `call_tool("get_billing_summary", ...)` | `GET /v1/billing/wallets/{id}/usage` |

Request payload must also change: guide uses `invariants`/`action`/`formula`,
API expects `properties` array with `name`/`expression`/`scope`/`language`.

**File:** `seed-products/formal-gatekeeper.md` (Chapters 1, 2, 4, 7, 9)
**Status:** PENDING — guide file not in this repo

### P1 — JSON block regex bug (guide file)

`PlanParser.JSON_BLOCK_RE` regex:
```
r"```(?:json)?\s*\n(\{.*?\})```"  # BUG: missing \s* before closing ```
```
Should be:
```
r"```(?:json)?\s*\n(\{.*?\})\s*```"  # FIXED
```

Standard markdown has a newline between `}` and closing ``` fence, which the
regex doesn't match.

**File:** `seed-products/formal-gatekeeper.md` (Chapter 3)
**Status:** PENDING — guide file not in this repo

### P2 — Auth header documentation (guide file)

Auth header format (`Authorization: Bearer YOUR_KEY`) is correct for the
gateway. The guide should specify that gatekeeper endpoints require `pro` tier
API keys (except `verify_proof` which is `free`).

**File:** `seed-products/formal-gatekeeper.md` (Chapter 1)
**Status:** PENDING — guide file not in this repo

---

## What Works Well (confirmed by audit)

- All 8 Python classes syntactically valid and functionally correct
- 13 invariants (6 filesystem, 4 economic, 3 network) logically sound
- Z3 negation trick (A AND NOT(I) → UNSAT = safe) correct
- Plan parser handles shell commands, inline transactions, pipe chains
- Proof cache: LRU eviction, TTL expiry, hash-based invalidation
- Test suite: 10 malicious + 8 safe + 5 edge cases comprehensive
- Compound plan translation correctly computes cumulative spending

## Gateway-side Notes

All gatekeeper endpoints are functional as of v1.4.1 (confirmed by
`TestAuditZ3Regression` in PR #103). The issue is solely in the guide's
use of the deprecated `POST /v1/execute` wrapper.

The guide should be updated to use direct REST endpoints. See
`tasks/external/formal-gatekeeper-skill.md` for the correct API reference.
