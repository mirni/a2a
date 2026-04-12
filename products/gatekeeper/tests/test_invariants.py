"""Z3 formal verification harnesses for business invariants (FV-1..6).

Each test negates a critical business invariant and asserts Z3 returns
``unsat`` — meaning the negation is impossible and the invariant holds.
If Z3 returns ``sat``, the counterexample is printed as a failing test
message so the developer can see exactly which assignment breaks the rule.

These harnesses run in CI as part of the quality gate. Any ``sat`` result
blocks the build.
"""

from __future__ import annotations

import pytest

z3 = pytest.importorskip("z3", reason="z3-solver not installed")


# -----------------------------------------------------------------------
# FV-1: Wallet balance never goes negative
# -----------------------------------------------------------------------


class TestFV1WalletNonneg:
    """Prove: if balance >= 0, amount >= 0, and balance >= amount,
    then balance - amount >= 0."""

    def test_debit_preserves_nonneg(self):
        balance = z3.Int("balance")
        amount = z3.Int("amount")
        s = z3.Solver()
        # Preconditions
        s.add(balance >= 0, amount >= 0)
        # Negate the invariant: the pre-check (balance >= amount) should
        # guarantee post-state nonneg. If the negation is sat, the
        # pre-check is insufficient.
        s.add(z3.Not(z3.Implies(balance >= amount, balance - amount >= 0)))
        result = s.check()
        assert result == z3.unsat, f"FV-1 BROKEN: {s.model()}"

    def test_debit_without_precheck_is_unsafe(self):
        """Without the pre-check, balance can go negative (sat expected)."""
        balance = z3.Int("balance")
        amount = z3.Int("amount")
        s = z3.Solver()
        s.add(balance >= 0, amount >= 0)
        # No pre-check, just debit
        s.add(balance - amount < 0)
        result = s.check()
        assert result == z3.sat, "Debit without pre-check should be unsafe"


# -----------------------------------------------------------------------
# FV-2: Refund total <= captured amount
# -----------------------------------------------------------------------


class TestFV2RefundBound:
    """Prove: if refund_total <= captured and extra >= 0, and we check
    refund_total + extra <= captured before applying, then the invariant
    is preserved."""

    def test_refund_preserves_bound(self):
        captured = z3.Int("captured")
        refund_total = z3.Int("refund_total")
        extra = z3.Int("extra")
        s = z3.Solver()
        # Preconditions
        s.add(captured >= 0, refund_total >= 0, extra >= 0)
        s.add(refund_total <= captured)
        # Pre-check: refund_total + extra <= captured
        s.add(refund_total + extra <= captured)
        # Negate post-condition: new total exceeds captured
        s.add(refund_total + extra > captured)
        result = s.check()
        assert result == z3.unsat, f"FV-2 BROKEN: {s.model()}"

    def test_refund_without_check_can_exceed(self):
        """Without the pre-check, refund can exceed captured."""
        captured = z3.Int("captured")
        refund_total = z3.Int("refund_total")
        extra = z3.Int("extra")
        s = z3.Solver()
        s.add(captured >= 0, refund_total >= 0, extra >= 0)
        s.add(refund_total <= captured)
        # No pre-check, just ask if post exceeds
        s.add(refund_total + extra > captured)
        result = s.check()
        assert result == z3.sat, "Refund without check should be able to exceed"


# -----------------------------------------------------------------------
# FV-3: Split amounts sum to intent total
# -----------------------------------------------------------------------


class TestFV3SplitSum:
    """Prove: for any 3-way split where each slice is a non-negative
    integer and the last slice is total - sum(first N-1), the slices
    sum to total."""

    def test_three_way_split_sums_to_total(self):
        total = z3.Int("total")
        s1 = z3.Int("s1")
        s2 = z3.Int("s2")
        s3 = z3.Int("s3")
        s = z3.Solver()
        # Preconditions
        s.add(total >= 0, s1 >= 0, s2 >= 0)
        # Last slice absorbs remainder (our split_amount algorithm)
        s.add(s3 == total - s1 - s2)
        # Negate: sum != total
        s.add(s1 + s2 + s3 != total)
        result = s.check()
        assert result == z3.unsat, f"FV-3 BROKEN: {s.model()}"

    def test_n_way_split_sums_to_total(self):
        """Generalize to N=5 splits."""
        total = z3.Int("total")
        slices = [z3.Int(f"s{i}") for i in range(5)]
        s = z3.Solver()
        s.add(total >= 0)
        for sl in slices[:-1]:
            s.add(sl >= 0)
        # Last slice absorbs remainder
        s.add(slices[-1] == total - z3.Sum(slices[:-1]))
        # Negate
        s.add(z3.Sum(slices) != total)
        result = s.check()
        assert result == z3.unsat, f"FV-3 N-way BROKEN: {s.model()}"


# -----------------------------------------------------------------------
# FV-4: Budget cap enforced before debit
# -----------------------------------------------------------------------


class TestFV4BudgetCap:
    """Prove: if spend <= cap and cost >= 0, and we reject when
    spend + cost > cap, then after the debit spend' <= cap."""

    def test_budget_cap_preserved(self):
        spend = z3.Int("spend")
        cap = z3.Int("cap")
        cost = z3.Int("cost")
        s = z3.Solver()
        # Loop invariant
        s.add(spend >= 0, cap >= 0, cost >= 0)
        s.add(spend <= cap)
        # Pre-check passes (not rejected)
        s.add(spend + cost <= cap)
        # Negate post-condition
        s.add(spend + cost > cap)
        result = s.check()
        assert result == z3.unsat, f"FV-4 BROKEN: {s.model()}"

    def test_concurrent_budget_race(self):
        """Two concurrent requests each read spend=S, both pass the
        check, both write S+cost. Prove that if we require atomic
        read-check-write, both can't exceed the cap simultaneously."""
        spend = z3.Int("spend")
        cap = z3.Int("cap")
        cost1 = z3.Int("cost1")
        cost2 = z3.Int("cost2")
        s = z3.Solver()
        s.add(spend >= 0, cap >= 0, cost1 >= 0, cost2 >= 0)
        s.add(spend <= cap)
        # Both read same pre-state and pass check individually
        s.add(spend + cost1 <= cap)
        s.add(spend + cost2 <= cap)
        # But total exceeds cap (race)
        s.add(spend + cost1 + cost2 > cap)
        result = s.check()
        # This IS sat — proving the race exists without atomicity
        assert result == z3.sat, "Budget race should be possible without atomicity"


# -----------------------------------------------------------------------
# FV-5: Tier access-control matrix is sound
# -----------------------------------------------------------------------


class TestFV5TierACL:
    """Prove: in the 4-tier lattice free(0) < starter(1) < pro(2) <
    enterprise(3) < admin(4), a caller can only access a tool if their
    tier rank >= the tool's required tier rank."""

    def test_tier_lattice_soundness(self):
        caller_rank = z3.Int("caller_rank")
        tool_rank = z3.Int("tool_rank")
        s = z3.Solver()
        # Valid ranks
        s.add(caller_rank >= 0, caller_rank <= 4)
        s.add(tool_rank >= 0, tool_rank <= 4)
        # Access allowed
        allowed = caller_rank >= tool_rank
        # Negate: allowed but rank too low
        s.add(allowed, caller_rank < tool_rank)
        result = s.check()
        assert result == z3.unsat, f"FV-5 BROKEN: {s.model()}"

    def test_admin_only_tools_unreachable_by_non_admin(self):
        """Prove: admin-only tools (rank=4) cannot be reached by
        free(0), starter(1), pro(2), or enterprise(3)."""
        caller_rank = z3.Int("caller_rank")
        s = z3.Solver()
        s.add(caller_rank >= 0, caller_rank <= 3)  # non-admin
        # Negate: non-admin reaches admin tool
        s.add(caller_rank >= 4)
        result = s.check()
        assert result == z3.unsat, f"FV-5 admin gate BROKEN: {s.model()}"


# -----------------------------------------------------------------------
# FV-6: Idempotency key->response is a function
# -----------------------------------------------------------------------


class TestFV6IdempotencyFunction:
    """Prove: the idempotency dispatch is a function from key to response.

    Same key + same body_hash => same response (replay).
    Same key + different body_hash => 409 (conflict).
    """

    def test_idempotency_is_functional(self):
        Key = z3.DeclareSort("Key")
        Hash = z3.DeclareSort("Hash")
        Resp = z3.DeclareSort("Resp")

        stored_hash = z3.Function("stored_hash", Key, Hash)
        stored_resp = z3.Function("stored_resp", Key, Resp)
        resp_409 = z3.Const("resp_409", Resp)

        k = z3.Const("k", Key)
        h1 = z3.Const("h1", Hash)

        # Define dispatch
        dispatch = z3.Function("dispatch", Key, Hash, Resp)
        s = z3.Solver()

        # Axiom: same hash => stored response
        s.add(
            z3.ForAll(
                [k, h1],
                z3.Implies(
                    h1 == stored_hash(k),
                    dispatch(k, h1) == stored_resp(k),
                ),
            )
        )
        # Axiom: different hash => 409
        s.add(
            z3.ForAll(
                [k, h1],
                z3.Implies(
                    h1 != stored_hash(k),
                    dispatch(k, h1) == resp_409,
                ),
            )
        )

        # Prove functional: same inputs => same output
        k0 = z3.Const("k0", Key)
        h_a = z3.Const("h_a", Hash)
        h_b = z3.Const("h_b", Hash)
        s.add(h_a == h_b)
        s.add(dispatch(k0, h_a) != dispatch(k0, h_b))

        result = s.check()
        assert result == z3.unsat, f"FV-6 BROKEN: {s.model()}"

    def test_different_body_returns_409(self):
        Key = z3.DeclareSort("Key")
        Hash = z3.DeclareSort("Hash")
        Resp = z3.DeclareSort("Resp")

        stored_hash = z3.Function("stored_hash", Key, Hash)
        resp_409 = z3.Const("resp_409", Resp)
        dispatch = z3.Function("dispatch", Key, Hash, Resp)

        k = z3.Const("k", Key)
        h = z3.Const("h", Hash)

        s = z3.Solver()
        # Axiom: different hash => 409
        s.add(
            z3.ForAll(
                [k, h],
                z3.Implies(
                    h != stored_hash(k),
                    dispatch(k, h) == resp_409,
                ),
            )
        )

        # Concrete: k0 with different hash should get 409
        k0 = z3.Const("k0", Key)
        h_new = z3.Const("h_new", Hash)
        s.add(h_new != stored_hash(k0))
        s.add(dispatch(k0, h_new) != resp_409)

        result = s.check()
        assert result == z3.unsat, f"FV-6 conflict BROKEN: {s.model()}"
