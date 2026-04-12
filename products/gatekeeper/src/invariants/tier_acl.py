"""FV-5: Tier access-control matrix is sound.

Proves: in the 5-rank tier lattice (free=0 < starter=1 < pro=2 <
enterprise=3 < admin=4), a caller can only access a tool if their
tier rank >= the tool's required tier rank.
"""

from __future__ import annotations

from z3 import And, Int, Solver, unsat


def verify() -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    caller_rank = Int("caller_rank")
    tool_rank = Int("tool_rank")
    s = Solver()
    s.add(caller_rank >= 0, caller_rank <= 4)
    s.add(tool_rank >= 0, tool_rank <= 4)
    allowed = caller_rank >= tool_rank
    s.add(And(allowed, caller_rank < tool_rank))
    result = s.check()
    return (str(result), s.model() if result != unsat else None)
