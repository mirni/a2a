# ADR-010: Path Parameter Error Semantics (403 vs 404)

**Status:** Accepted
**Date:** 2026-04-05
**Context:** Live payments audit 2026-04-05 (M4, M5)

## Context

The external payments audit raised two medium-severity findings about HTTP
status codes for path parameters that don't match a real resource:

- **M4**: `GET /v1/billing/wallets/<url-encoded-SQL>/balance` returns
  `403 forbidden` (ownership check) rather than `404` or `422`. The auditor
  noted this is "information-safe but inconsistent" — the response leaks that
  "you are not the owner of this (non-existent) wallet".
- **M5**: `POST /v1/identity/metrics` returns `405 Method Not Allowed`.
  The endpoint exists at `GET /v1/identity/metrics` (query_metrics), but no
  `POST` handler is registered at that exact path (POSTs go to
  `/v1/identity/agents/{agent_id}/metrics` or `/v1/identity/metrics/ingest`).

## Decision

### M4 — Keep 403 for non-owned wallets

We deliberately return `403 Forbidden` (ownership check) for wallet-balance
lookups on any `agent_id` the caller does not own, regardless of whether the
wallet exists in the database. This prevents **enumeration attacks** where an
attacker could distinguish between "wallet exists but not yours" (403) and
"wallet doesn't exist" (404) and map out valid agent IDs.

The ownership check runs **before** any database read. The response contains
no information about whether the target wallet exists. From a security
standpoint, 403 for both cases is the correct BOLA-prevention posture
(OWASP API1:2023).

The auditor's own note confirms this is "information-safe". We accept the
"inconsistency" trade-off because the security guarantee is more valuable
than strict REST semantics here.

### M5 — Accept 405 as correct REST behavior

`GET /v1/identity/metrics` is a query endpoint for agent reputation metrics.
A `POST` to the same path correctly returns `405 Method Not Allowed` because
that method is not supported at that path. The audit tool's test was mapped
to the wrong path; the actual POST endpoints are:

- `POST /v1/identity/agents/{agent_id}/metrics` — submit metrics for an agent
- `POST /v1/identity/metrics/ingest` — bulk ingest (admin-scoped)

The `405` is wrapped in our standard RFC 9457 `application/problem+json`
envelope via `_http_exception_handler` in `gateway/src/app.py`, so error
format is consistent.

**Follow-up:** the OpenAPI spec and `docs/api-reference.md` must clearly
disambiguate these three paths so clients don't guess at `/v1/identity/metrics`
for POST.

## Consequences

- **Security > strict REST**: BOLA protection takes priority over returning
  the "most informative" status code. The 403-before-404 pattern is applied
  consistently on all wallet, intent, escrow, and subscription routes.
- **Documentation burden**: API reference must explicitly list which path
  accepts which methods. Tools that discover endpoints via `OPTIONS` get the
  correct allowed-methods list.
- **Audit re-running**: the audit tool should be updated to recognise that
  `403 on wallet/{id}/balance` is the intended enumeration-prevention
  behavior and not a bug.

## Alternatives considered

1. **Return 404 for non-existent wallets, 403 for non-owned**: rejected.
   Leaks existence of arbitrary agent IDs, enabling enumeration.
2. **Return 404 for both**: rejected. Breaks the principle that 404 means
   "not found" — it would be lying for genuinely existing wallets.
3. **Return 422 for "no such agent"**: rejected. 422 is for validation
   errors on the request body; path params that format-validate but don't
   resolve aren't a 422 case.

## References

- OWASP API Security Top 10 2023 — API1: Broken Object Level Authorization
- RFC 7231 §6.5.3 (403 Forbidden) and §6.5.4 (404 Not Found)
- RFC 9457 (Problem Details for HTTP APIs)
- Audit report: `reports/external/live-payments-audit-2026-04-05-combined.md`
