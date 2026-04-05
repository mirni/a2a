# ADR-005: Idempotency Keys for Mutating Endpoints

**Date:** 2026-03-30
**Status:** Accepted
**Role:** Architect

## Context

Mobile networks, retries, and agent-to-agent orchestration all produce
duplicate requests. Payment, deposit, capture, and refund operations
**must** be idempotent: the second identical request must not debit a
wallet twice. Network timeouts are expected; duplicate submissions are
normal.

## Decision

**Mutating endpoints accept an optional `Idempotency-Key` header**
(RFC draft, Stripe-compatible). Behavior:

1. Client generates a UUID-like key per logical operation and sends it
   on every retry of that operation.
2. Gateway looks up the key in the product's idempotency table:
   - If found with matching request fingerprint → return stored response.
   - If found with mismatched fingerprint → 409 `idempotency_key_reused`.
   - If not found → process request, store response + key, return.
3. Keys expire after 24 hours (configurable per-product).

For **Stripe webhooks** we additionally dedup on `session_id` via a
unique index (`stripe_sessions.session_id`) — at-least-once delivery
from Stripe means duplicates are guaranteed, not hypothetical.

For **payment intents**, the intent ID itself acts as the idempotency
anchor: `capture(intent_id)` uses an atomic compare-and-set transition
`PENDING → CAPTURED` so double-capture returns 409 (see ADR-008).

## Alternatives Considered

- **Timestamp-based deduplication.** Fragile under clock skew and retry
  windows. Rejected.
- **Client-chosen request IDs without server storage.** Can't prevent
  replays at the server level. Rejected.
- **Database unique constraints only.** Works for Stripe sessions but
  doesn't cover ad-hoc idempotency for deposits/transfers. Supplement,
  not replacement.

## Consequences

### Positive

- Safe retries by clients, SDKs, and third-party orchestrators
- Compatible with Stripe's Idempotency-Key pattern — customers' mental
  model transfers
- Prevents money-loss bugs from retries

### Negative

- Extra write per mutating request (idempotency table)
- Clients must remember to send the header (but SDKs do this by default)
- Key storage must be garbage-collected (24h TTL)

### Mitigations

- SDKs auto-generate keys from UUID4 on every request
- Idempotency table is VACUUMed nightly
- Unit tests enforce that every mutating tool echoes back
  `transaction_id` on retries (see `test_deposit_idempotency.py`)

## Related

- ADR-008: Capture atomicity & compensation
- Code: `products/payments/src/idempotency.py`,
  `gateway/src/tools/billing.py::_deposit`
- Reference: https://stripe.com/docs/api/idempotent_requests
