# Agent Task Planning Guide

**Audience:** Claude agents (and humans) working in this repo.
**Purpose:** Reduce the rework rate on audit remediation and feature work
by forcing a specific planning shape *before* code is touched. Built on
Hoare logic where the task is about state transitions, arithmetic, or
access control; built on pragmatism everywhere else.

This file is short on theory and long on recipe. If you are mid-task and
need a reminder, jump to *"The 5-step planning template"*.

---

## When to plan formally

Not every task needs Hoare triples. Use this decision tree:

| Task shape                                         | Planning style                 |
|----------------------------------------------------|--------------------------------|
| Typo, copy tweak, comment fix                      | Just do it.                    |
| Single-file refactor, no behaviour change          | Brief bullet plan.             |
| New API endpoint, new model, new tool              | Full 5-step template.          |
| Touches money, balances, refunds, fees, splits     | Full template + Hoare triples. |
| Touches tier gates / access control / auth         | Full template + Hoare triples. |
| Touches state machines (intents, escrows, subs)    | Full template + Hoare triples. |
| Touches rate limiter / budget cap / idempotency    | Full template + Hoare triples. |
| Concurrency, async, locking, race-condition fixes  | Full template + Hoare triples. |
| Anything the external audit has flagged twice      | Full template + Hoare triples. |

If in doubt, write the triples. The cost is ~5 minutes; the cost of
shipping a budget-cap regression is a NO-GO audit.

---

## Hoare logic in 90 seconds

A Hoare triple is written `{P} C {Q}`:

- **P** — precondition, what must hold *before* executing `C`.
- **C** — the code / command / operation.
- **Q** — postcondition, what must hold *after* `C` completes.

Read as: *"if P holds and we run C, then Q will hold when C finishes."*

For loops (and async polling loops) you also need an **invariant** `I`
that holds before every iteration, holds after every iteration, and on
exit implies your postcondition.

### Three worked examples from this codebase

**Wallet debit:**
```
{ balance ≥ 0  ∧  amount ≥ 0  ∧  balance ≥ amount }
  balance := balance − amount
{ balance ≥ 0 }
```
The `balance ≥ amount` clause in P is the pre-check we need to prove is
enforced *before* the debit in `wallet.debit()`. If you cannot point at
the code that enforces it, you have a bug — write the test first.

**Refund application:**
```
{ captured ≥ 0  ∧  refunded ≥ 0  ∧  refunded + extra ≤ captured  ∧  extra ≥ 0 }
  refunded := refunded + extra
{ refunded ≤ captured }
```
The v1.2.7 `+$1 balance drift` finding is a failure of the precondition
clause `refunded + extra ≤ captured` — the bookkeeper allowed `extra` to
push the sum past `captured`. The fix is enforcing P, not patching Q.

**Budget cap enforcement (loop invariant):**
```
Invariant I : spend ≤ cap

{ I ∧ cost ≥ 0 }
  if spend + cost > cap then reject
  else spend := spend + cost
{ I }
```
Every request is a loop iteration. `I` holds forever if and only if
the check-then-increment is atomic *and* read/write hit the same store.
v1.2.7 NEW-CRIT-7-2-7 is `I` being violated because two stores were
used; the fix is to pick one canonical store and let Z3 prove the
invariant holds.

---

## The 5-step planning template

Paste this skeleton into every non-trivial task file or PR description.

### 1. Problem statement
One paragraph: what is broken or missing, *who* filed it (audit persona,
user issue, internal observation), and what "done" looks like. No
solution yet.

### 2. Preconditions & postconditions

List the `{P}` and `{Q}` for every non-trivial operation you will touch.
If the task is about money or state, also include the **invariants** `I`
that must never be violated across the operation's lifetime.

Good shape:

```
Operation: POST /v1/payments/intents/{id}/refund

P:  intent.state ∈ {captured, partially_refunded}
    ∧  refund_amount > 0
    ∧  refund_amount ≤ intent.captured_amount − intent.refunded_amount
    ∧  caller_agent_id = intent.merchant_id  (ownership)
    ∧  idempotency_key_unused_or_matches_body

Q:  intent.refunded_amount' = intent.refunded_amount + refund_amount
    ∧  wallet[payer].balance' = wallet[payer].balance + refund_amount
    ∧  wallet[merchant].balance' = wallet[merchant].balance − refund_amount
    ∧  intent.state' = (refunded if refund_amount = captured_amount
                        else partially_refunded)

I:  intent.refunded_amount ≤ intent.captured_amount   (monotone, inviolable)
    ∧  wallet[*].balance ≥ 0                          (no negatives anywhere)
    ∧  Σ wallet.balance  +  Σ intent.held  =  constant  (conservation of money)
```

The conservation-of-money invariant is the real test: if your refund
path changes it, you have a double-credit bug. Always state it.

### 3. Red phase — write the tests

Before touching source code, write the failing tests. Each triple above
maps to:

- A **happy-path** test (P holds → Q holds after).
- A **boundary** test (P almost fails: refund amount equal to captured −
  refunded, assert exactly-at-boundary succeeds).
- A **negative** test (P is violated: refund too large, refund on a
  non-captured intent, refund by non-owner → expect RFC 9457 4xx).
- An **invariant** test: run N random operations from Hypothesis, assert
  the invariant holds after every step.
- If the task is P0 from an audit, a **sandbox-parity** test that hits
  `sandbox.greenhelix.net` with real API keys, not the in-process client.
  Unit tests alone have failed to catch audit findings 5 releases in a
  row; sandbox parity is now table stakes.

Run the tests. Confirm they fail. Paste the red output into the task
file — *proof* that the tests see the bug.

### 4. Green phase — minimum code to pass

Write the smallest code change that makes every red test pass. No
"while I'm here" cleanup. No new helpers unless the test demands one.
If you are tempted to refactor, open a P2 follow-up instead.

### 5. Refactor & verify

- Run the full module test suite (`python -m pytest products/<module>/
  gateway/tests/`). Nothing else may break.
- Run `ruff format --check` and `ruff check`. Clean.
- If the task touched one of the 6 paid-path invariants (see
  `tasks/backlog/repo-hygiene-and-formal-verification.md` Phase 4), run
  the corresponding Z3 harness in `products/gatekeeper/tests/
  test_invariants.py` and confirm it stays `unsat`.
- Update `logs/MASTER_LOG.md`. Open PR. Wait for CI.

---

## Translating Hoare triples into executable tests

You do not need a theorem prover for most tasks. Three layers of rigour,
pick the one that matches the stakes:

### Layer 1 — Plain assert (cheap, everywhere)

```python
def test_refund_preserves_bookkeeping():
    intent = create_intent(amount=Decimal("100"))
    capture(intent)
    pre_merchant = wallet(merchant).balance
    pre_payer = wallet(payer).balance

    refund(intent, amount=Decimal("30"))

    # Postcondition
    assert intent.refunded_amount == Decimal("30")
    # Invariant: conservation
    assert wallet(merchant).balance == pre_merchant - Decimal("30")
    assert wallet(payer).balance == pre_payer + Decimal("30")
```

Use for all happy-path and boundary tests.

### Layer 2 — Hypothesis property-based (medium, for arithmetic)

```python
from hypothesis import given, strategies as st
from decimal import Decimal

@given(
    captured=st.decimals(min_value="0.01", max_value="10000",
                         places=2, allow_nan=False),
    n_refunds=st.integers(min_value=1, max_value=20),
    data=st.data(),
)
def test_refund_monotone(captured, n_refunds, data):
    intent = create_intent(amount=captured)
    capture(intent)

    total_refunded = Decimal("0")
    for _ in range(n_refunds):
        remaining = captured - total_refunded
        if remaining == 0:
            break
        chunk = data.draw(st.decimals(min_value="0.01",
                                      max_value=str(remaining),
                                      places=2))
        refund(intent, chunk)
        total_refunded += chunk
        # Invariant checked every step
        assert intent.refunded_amount == total_refunded
        assert intent.refunded_amount <= captured
```

Use for anything with decimal arithmetic, splits, fees, or
multi-step state machines.

### Layer 3 — Z3 invariant harness (expensive, for the 6 paid-path rules)

See `products/gatekeeper/src/invariants/` (to be created in Phase 4 of
the repo-hygiene task). Each harness *proves* the triple for all inputs
in the integer/rational lattice, not just the samples Hypothesis picks.

```python
from z3 import Int, Solver, Implies, Not, unsat

def test_wallet_debit_never_negative():
    balance = Int("balance")
    amount  = Int("amount")
    s = Solver()
    s.add(balance >= 0)
    s.add(amount >= 0)
    # Negate the triple: we want to prove it holds, so UNSAT = proven
    s.add(Not(Implies(balance >= amount, balance - amount >= 0)))
    assert s.check() == unsat
```

If `s.check()` returns `sat`, the solver has found a counterexample —
print `s.model()` and you have a bug in your Hoare triple or in the
code. Use for the invariants listed in Phase 4 of the repo-hygiene
plan: wallet nonneg, refund ≤ captured, split sum, budget cap, tier
access-control matrix, idempotency determinism.

---

## Common planning mistakes to avoid

1. **Writing Q without P.** "The balance is right at the end" is not a
   specification — under what starting condition? Every Q needs its P.

2. **Forgetting the invariant.** Refund tests that check only the
   refund row forget the conservation-of-money invariant across *both*
   wallets. Invariants are the tests that catch the bookkeeping drift.

3. **Testing the implementation, not the specification.** "The code
   calls `wallet.debit()` twice" is an implementation detail. "The
   merchant wallet decreases by exactly the refund amount" is the spec.
   Test the spec.

4. **Concurrency as an afterthought.** If two requests can interleave,
   state the triple for the *interleaved* case too. The v1.2.4 P0-4
   (idempotency race) and v1.2.7 NEW-CRIT-7-2-7 (budget cap split
   stores) are both failures to do this.

5. **Running the solver on code instead of on models.** Z3 does not read
   Python. You write a model of the code's arithmetic; the solver
   proves the model satisfies the triple. Keeping the model in lockstep
   with the code is a manual discipline — review the model any time you
   touch the real function.

6. **Skipping the red phase.** If you did not see the test fail, you do
   not know the test tests anything. Paste the red output into the task
   file. CLAUDE.md already requires this; Hoare triples do not excuse
   you from it.

---

## Task file skeleton

When you create a file under `tasks/backlog/`, use this skeleton:

```markdown
# <short task title>

## Problem
<one paragraph>

## Specification
Operation: <path or function>

P:  <precondition clauses, one per line>
Q:  <postcondition clauses>
I:  <invariants that must always hold>   (optional for trivial tasks)

## Tests to write (red phase)
- [ ] happy-path: <triple name>
- [ ] boundary: <edge case>
- [ ] negative: <P violated → expected error>
- [ ] invariant property test (Hypothesis)
- [ ] sandbox-parity (if audit P0)

## Files touched
- <path>:<line> — <what changes>

## Acceptance
- Red output pasted before code written
- Full module suite green
- ruff + mypy clean
- Z3 harness `<name>` still unsat (if applicable)
- `logs/MASTER_LOG.md` updated
- PR opened, CI green including staging
```

---

## Quick cross-references

- `CLAUDE.md` — TDD cycle, branch/PR rules, logging rules. This guide
  assumes you are following it.
- `tasks/backlog/repo-hygiene-and-formal-verification.md` — the six
  Z3 invariants every paid-path change will eventually be checked
  against.
- `tasks/backlog/v1.2.4-audit-p1.md` and
  `tasks/backlog/v1.2.7-audit-remediation.md` — worked examples of P0
  tasks that needed Hoare reasoning (budget cap, refund drift,
  idempotency race, tier access gate).
- `products/gatekeeper/` — the Z3 + AWS Lambda pipeline the FV work
  plugs into.
