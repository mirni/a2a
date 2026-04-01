# Security Sprint Items — Idempotency + Stripe Dedup

**Priority:** Sprint (S1, S2)
**Source:** Market Readiness Audit 2026-04-01
**Effort:** 3 days

## S1: Add Idempotency Keys to Financial Operations

### Problem
Only `create_intent` supports `Idempotency-Key` header. Three critical financial operations lack it:
- `capture_intent`
- `release_escrow`
- `cancel_escrow`

Network retries on these operations could cause double-capture or double-release.

### Implementation
- Add `Idempotency-Key` header support to the 3 operations
- Store idempotency keys in DB with TTL (24h)
- Return cached response on duplicate key
- Follow same pattern as existing `create_intent` implementation

## S2: Fix Stripe Webhook Deduplication

### Problem
`gateway/src/stripe_checkout.py` uses hybrid dedup:
- In-memory set `_processed_sessions` (line 33) — lost on restart
- DB table `processed_stripe_sessions` — persistent

After process restart, a replayed webhook would pass the in-memory check and process again. The DB check exists but is secondary.

### Fix
- Make DB the primary dedup check (check DB first, then in-memory cache)
- In-memory set becomes a performance optimization only
- Add cleanup job for old entries (>30 days)

## Acceptance Criteria
- [ ] All 4 financial ops support `Idempotency-Key`
- [ ] Duplicate idempotency key returns cached response (not re-execution)
- [ ] Stripe dedup survives process restart
- [ ] Tests cover all scenarios
