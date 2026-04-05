# ADR-008: Capture Atomicity via Compare-and-Set + Compensation

**Date:** 2026-04-05
**Status:** Accepted
**Role:** Architect

## Context

A payment capture crosses two databases: `payments.db` (intent status,
settlement row) and `billing.db` (wallet debit + credit). SQLite does
not support distributed transactions and we have no global coordinator.

The audit (reports/external/live-payments-audit-2026-04-05-combined.md)
identified three related critical bugs:

- **C2:** mid-capture failure left wallet debited but intent status
  `PENDING` → money disappeared
- **C3:** with status stuck at `PENDING`, a concurrent retry re-passed
  the status check and re-debited
- **C4:** `refund_intent(intent_id)` with status `PENDING` treated the
  intent as unfunded and no-op'd, losing the debited funds permanently

## Decision

**`capture(intent_id)` implements atomic reservation via compare-and-set
on intent status, followed by wallet operations, followed by
compare-and-set to finalize. On any failure mid-sequence, the engine
reverses the wallet operations directly via storage (bypassing wrappers)
and reverts the status to `PENDING`.**

Sequence:

```
1. CAS payments.db: intent.status PENDING → CAPTURED      (lock)
   ├─ fail (not PENDING) → 409 invalid_state (prevents C3 double-capture)
   └─ ok → continue
2. billing.db: debit payer wallet (strict, no-overdraft)
   ├─ fail → CAS CAPTURED → PENDING, raise
   └─ ok → continue
3. billing.db: credit payee wallet
   ├─ fail → credit payer (reverse), CAS CAPTURED → PENDING, raise
   └─ ok → continue
4. payments.db: insert settlement row
   ├─ fail → reverse (2) + (3), CAS CAPTURED → PENDING, raise
   └─ ok → continue
5. CAS payments.db: intent.status CAPTURED → SETTLED      (finalize)
```

The `CAPTURED` state is a short-lived "in-flight" state that blocks
concurrent captures (C3) and signals to refund code that funds **have**
been moved and must be reversed if refund is requested mid-capture (C4).

Compensation uses `storage.atomic_currency_debit_strict` /
`storage.atomic_currency_credit` directly (not `wallet.deposit()`)
so that compensation cannot itself be intercepted by wrappers.

## Alternatives Considered

- **Two-phase commit (2PC).** No coordinator; too much infra for MVP.
  Rejected.
- **Saga pattern with explicit compensation transactions.** This is
  effectively what we do, inlined in `capture()`. Formalizing as a
  generic saga framework is overkill for 2 steps. Rejected for now.
- **Single-DB (merge payments + billing).** Breaks product boundaries
  (ADR-002). Possible future refactor if capture remains the only
  cross-DB op. Deferred.

## Consequences

### Positive

- Fixes C2, C3, C4 with a single cohesive mechanism
- No partial-state money loss — failures leave state equal to
  pre-capture state (modulo CAPTURED→PENDING revert)
- Refund logic (`refund_intent`) can rely on status `CAPTURED`/`SETTLED`
  always meaning "funds moved"

### Negative

- Compensation code must be kept in lockstep with forward path
- SQLite `UPDATE ... WHERE status = ?` relies on `cursor.rowcount == 1`
  (must run in a single connection; WAL mode handles concurrency)
- An operator killing the process between step 2 and step 3 leaves
  `CAPTURED` status with partial wallet effects — detectable by the
  invariant checker (future cron job)

### Mitigations

- Three dedicated tests:
  - `test_capture_deposit_failure_preserves_payer_balance`
  - `test_double_capture_rejected_with_invalid_state`
  - `test_capture_insufficient_balance_leaves_intent_pending`
- Post-capture reconciliation: for all intents in `CAPTURED` > 60s,
  verify matching settlement row exists; if not, manually reverse.
  (Planned as nightly job)

## Related

- ADR-002: SQLite-per-product
- ADR-005: Idempotency keys
- Code: `products/payments/src/engine.py::capture`,
  `products/payments/src/storage.py::compare_and_set_intent_status`
- Audit: `reports/external/live-payments-audit-2026-04-05-combined.md`
