# ADR-009: Authentication and Rate Limiting Architecture

**Date:** 2026-03-30
**Status:** Accepted
**Role:** Architect

## Context

The gateway is a public endpoint serving money-moving operations for
autonomous agents. We need authentication that:

- Doesn't require interactive sign-in (agents can't click consent)
- Scopes access per-tier (free, starter, team, pro, enterprise)
- Enables per-customer rate limiting and usage metering
- Is simple enough for agents to embed in SDK constructors

And we need rate limiting that:

- Prevents abuse from unauthenticated clients (public endpoints)
- Prevents a single authenticated customer from exhausting resources
- Is cheap enough to enforce on every request (<1ms overhead)

## Decision

### Authentication: API keys

**Opaque bearer tokens of the form `a2a_{tier}_{24_hex_chars}`** passed
via `Authorization: Bearer <key>` header. Keys are:

- Generated at signup with cryptographic randomness
- Stored hashed (SHA-256) in `paywall.db` (never plaintext)
- Scoped to a tier embedded in the key prefix (cached at lookup)
- Revocable via admin endpoint (key hash → disabled flag)

No OAuth, no JWT for customer auth — the agent always carries the key.

### Rate limiting: token bucket, multi-tier

**Three independent limiters operating in sequence** (first to deny
rejects the request):

1. **Per-IP public limiter** on unauthenticated endpoints
   (`/v1/pricing`, `/v1/health`, `/.well-known/agent-card.json`):
   60 req/min per IP, burst 120. Implemented in
   `gateway/src/public_rate_limit.py`.

2. **Per-key tier limiter** on authenticated endpoints:
   free = 100/h, starter = 1000/h, pro = 10000/h, enterprise = 100000/h.
   Rates configured in `pricing.json` under `tiers.*.rate_limit_per_hour`.
   Burst allowance = per-tier `burst_allowance`.

3. **Per-tool cost limiter** enforced via wallet balance: each tool has
   a price in the catalog; `paywall.db` debits the wallet on each call.
   See ADR-006 for arithmetic.

Rate limit state is held in process memory (per-worker) with sliding
window. When we run multiple workers, we accept slight over-limit drift
at per-worker granularity — true distributed limiting (Redis) is
deferred until it matters.

## Alternatives Considered

- **JWT tokens.** Would let us embed tier + customer_id without DB
  lookup per request, but adds signing key rotation complexity and
  revocation becomes harder. Rejected for v1.
- **mTLS.** Harder for agents to provision. Good for enterprise B2B,
  deferred.
- **Redis-backed distributed rate limiter.** Needed eventually; deferred
  until single-host limits bite.
- **Separate API for auth (Keycloak, Auth0).** Extra service, extra
  latency, extra cost. Rejected for MVP.

## Consequences

### Positive

- O(1) lookup per request (single hash+select)
- Simple mental model: one key per agent, one wallet per key
- Keys rotate by revoking + reissuing — no token expiry to manage
- Multi-layer limiter protects against IP abuse AND noisy tenant

### Negative

- Key compromise = full account access until revocation (mitigated by
  monitoring + instant revocation)
- Per-worker rate limiting drifts up to Nx the limit with N workers
- Plain-text keys in env vars/files for customers (standard risk)

### Mitigations

- Auth failure spike alert (`AuthFailureSpike`) flags credential
  stuffing in real time
- Keys are logged hashed, never plaintext (see
  `products/shared/src/logging.py`)
- Customers can rotate keys via admin API without downtime
- Cloudflare WAF + IP allow-lists provide an outer ring of defense

## Related

- ADR-004: RFC 9457 errors
- Code: `gateway/src/deps/auth.py`, `gateway/src/deps/rate_limit.py`,
  `products/paywall/src/storage.py`
- Pricing: `pricing.json` → `tiers.*.rate_limit_per_hour`
- Runbook: [`error-rate-triage.md`](../infra/runbooks/error-rate-triage.md) §5 (401 spike)
