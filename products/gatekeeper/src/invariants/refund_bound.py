"""FV-2: Refund total <= captured amount.

Proves: if refund_total <= captured and we check
refund_total + extra <= captured before applying, the invariant holds.
"""

from __future__ import annotations

from z3 import Int, Solver, unsat


def verify() -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    captured = Int("captured")
    refund_total = Int("refund_total")
    extra = Int("extra")
    s = Solver()
    s.add(captured >= 0, refund_total >= 0, extra >= 0)
    s.add(refund_total <= captured)
    s.add(refund_total + extra <= captured)
    s.add(refund_total + extra > captured)
    result = s.check()
    return (str(result), s.model() if result != unsat else None)
