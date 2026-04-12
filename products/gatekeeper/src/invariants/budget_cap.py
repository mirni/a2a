"""FV-4: Budget cap enforced before debit.

Proves: if spend <= cap and cost >= 0, and we reject when
spend + cost > cap, then after accepting spend' = spend + cost <= cap.
"""

from __future__ import annotations

from z3 import Int, Solver, unsat


def verify() -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    spend = Int("spend")
    cap = Int("cap")
    cost = Int("cost")
    s = Solver()
    s.add(spend >= 0, cap >= 0, cost >= 0)
    s.add(spend <= cap)
    s.add(spend + cost <= cap)
    s.add(spend + cost > cap)
    result = s.check()
    return (str(result), s.model() if result != unsat else None)
