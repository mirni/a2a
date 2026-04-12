"""FV-3: Split amounts sum to intent total.

Proves: for any N-way split where each slice >= 0 and the last slice
absorbs the remainder, the slices sum to the total.
"""

from __future__ import annotations

from z3 import Int, Not, Solver, Sum, unsat


def verify(n: int = 3) -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    total = Int("total")
    slices = [Int(f"s{i}") for i in range(n)]
    s = Solver()
    s.add(total >= 0)
    for sl in slices[:-1]:
        s.add(sl >= 0)
    s.add(slices[-1] == total - Sum(slices[:-1]))
    s.add(Not(Sum(slices) == total))
    result = s.check()
    return (str(result), s.model() if result != unsat else None)
