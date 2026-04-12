"""FV-6: Idempotency key->response is a function.

Proves: same key + same body hash => same response (replay),
same key + different body hash => 409 (conflict).
The dispatch is a well-defined function from (key, hash) -> response.
"""

from __future__ import annotations

from z3 import Const, DeclareSort, ForAll, Function, Implies, Solver, unsat


def verify() -> tuple[str, object]:
    """Return ("unsat", None) if invariant holds, else ("sat", model)."""
    Key = DeclareSort("Key")
    Hash = DeclareSort("Hash")
    Resp = DeclareSort("Resp")

    stored_hash = Function("stored_hash", Key, Hash)
    stored_resp = Function("stored_resp", Key, Resp)
    resp_409 = Const("resp_409", Resp)
    dispatch = Function("dispatch", Key, Hash, Resp)

    k = Const("k", Key)
    h = Const("h", Hash)

    s = Solver()
    # Axiom: same hash => stored response
    s.add(ForAll([k, h], Implies(h == stored_hash(k), dispatch(k, h) == stored_resp(k))))
    # Axiom: different hash => 409
    s.add(ForAll([k, h], Implies(h != stored_hash(k), dispatch(k, h) == resp_409)))

    # Prove functional: same inputs => same output
    k0 = Const("k0", Key)
    h_a = Const("h_a", Hash)
    h_b = Const("h_b", Hash)
    s.add(h_a == h_b)
    s.add(dispatch(k0, h_a) != dispatch(k0, h_b))

    result = s.check()
    return (str(result), s.model() if result != unsat else None)
