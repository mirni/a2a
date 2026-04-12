"""FV-1: Wallet balance never goes negative.

Proves: if balance >= 0, amount >= 0, and balance >= amount (pre-check),
then balance - amount >= 0 (post-state non-negative).
"""

from __future__ import annotations

from z3 import Implies, Int, Not, Solver, unsat


def verify() -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    balance = Int("balance")
    amount = Int("amount")
    s = Solver()
    s.add(balance >= 0, amount >= 0)
    s.add(Not(Implies(balance >= amount, balance - amount >= 0)))
    result = s.check()
    return (str(result), s.model() if result != unsat else None)
