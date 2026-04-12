"""Z3 formal verification invariant harnesses.

Each module defines a business invariant as a Z3 formula and exposes
a ``verify()`` function that returns ``(result, model_or_none)``.

Available invariants:
  wallet_nonneg   — FV-1: wallet balance never goes negative
  refund_bound    — FV-2: refund total <= captured amount
  split_sum       — FV-3: split amounts sum to intent total
  budget_cap      — FV-4: budget cap enforced before debit
  tier_acl        — FV-5: tier access-control matrix is sound
  idempotency     — FV-6: idempotency key->response is a function
"""
