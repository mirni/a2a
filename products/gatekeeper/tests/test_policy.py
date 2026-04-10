"""Tests for the JSON policy DSL and its Z3 SMT-LIB2 compiler.

Gatekeeper v1.2.2 introduces a high-level JSON policy language that lets
integrators express invariants without writing raw SMT-LIB2. Each policy
is compiled deterministically to an SMT-LIB2 string which the existing
Lambda verifier consumes unchanged.

These tests cover:
* Schema validation (required/forbidden fields, type checks).
* Deterministic compilation (same input → same SMT2 output).
* Round-trip SMT-LIB2 emission of every supported operator.
* Happy-path Z3 evaluation when z3-solver is installed.
"""

from __future__ import annotations

import pytest

from products.gatekeeper.src.policy import (
    JsonPolicy,
    PolicyCompileError,
    compile_policy_to_smt2,
)

try:
    from z3 import Solver, parse_smt2_string, sat, unsat  # noqa: F401

    _Z3_AVAILABLE = True
except ImportError:  # pragma: no cover - environments without z3
    _Z3_AVAILABLE = False


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestJsonPolicySchema:
    def test_minimal_policy_parses(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "positive_x",
                "variables": [{"name": "x", "type": "int"}],
                "assertions": [{"op": ">", "args": ["x", 0]}],
            }
        )
        assert policy.name == "positive_x"
        assert policy.variables[0].name == "x"
        assert policy.variables[0].type == "int"

    def test_empty_assertions_rejected(self):
        with pytest.raises(Exception):
            JsonPolicy.model_validate(
                {
                    "name": "empty",
                    "variables": [{"name": "x", "type": "int"}],
                    "assertions": [],
                }
            )

    def test_extra_fields_rejected(self):
        with pytest.raises(Exception):
            JsonPolicy.model_validate(
                {
                    "name": "bad",
                    "variables": [{"name": "x", "type": "int"}],
                    "assertions": [{"op": ">", "args": ["x", 0]}],
                    "bogus": "field",
                }
            )

    def test_invalid_variable_type_rejected(self):
        with pytest.raises(Exception):
            JsonPolicy.model_validate(
                {
                    "name": "bad_type",
                    "variables": [{"name": "x", "type": "complex"}],
                    "assertions": [{"op": ">", "args": ["x", 0]}],
                }
            )


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class TestPolicyCompiler:
    def test_single_int_variable_gt(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "positive",
                "variables": [{"name": "x", "type": "int"}],
                "assertions": [{"op": ">", "args": ["x", 0]}],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(declare-const x Int)" in smt2
        assert "(assert (> x 0))" in smt2

    def test_real_variable_le(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "bounded_rate",
                "variables": [{"name": "rate", "type": "real"}],
                "assertions": [{"op": "<=", "args": ["rate", 0.25]}],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(declare-const rate Real)" in smt2
        assert "(assert (<= rate (/ 25 100)))" in smt2 or "(assert (<= rate 0.25))" in smt2

    def test_bool_variable(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "flag",
                "variables": [{"name": "active", "type": "bool"}],
                "assertions": [{"op": "==", "args": ["active", True]}],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(declare-const active Bool)" in smt2
        # == on bool should become (= active true)
        assert "(= active true)" in smt2

    def test_variable_with_constant_value_emits_equality(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "const_total",
                "variables": [
                    {"name": "alice", "type": "int"},
                    {"name": "total", "type": "int", "value": 100},
                ],
                "assertions": [{"op": ">", "args": ["alice", 0]}],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(declare-const total Int)" in smt2
        assert "(assert (= total 100))" in smt2

    def test_nested_expression_balance_conservation(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "balance_conservation",
                "variables": [
                    {"name": "alice", "type": "int"},
                    {"name": "bob", "type": "int"},
                    {"name": "total", "type": "int", "value": 1000},
                ],
                "assertions": [
                    {"op": ">=", "args": ["alice", 0]},
                    {"op": ">=", "args": ["bob", 0]},
                    {
                        "op": "==",
                        "args": [{"op": "+", "args": ["alice", "bob"]}, "total"],
                    },
                ],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(declare-const alice Int)" in smt2
        assert "(declare-const bob Int)" in smt2
        assert "(= (+ alice bob) total)" in smt2

    def test_boolean_conjunction(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "conjunction",
                "variables": [
                    {"name": "x", "type": "int"},
                    {"name": "y", "type": "int"},
                ],
                "assertions": [
                    {
                        "op": "and",
                        "args": [
                            {"op": ">", "args": ["x", 0]},
                            {"op": ">", "args": ["y", 0]},
                        ],
                    }
                ],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(assert (and (> x 0) (> y 0)))" in smt2

    def test_implies(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "implication",
                "variables": [
                    {"name": "balance", "type": "int"},
                    {"name": "withdraw", "type": "int"},
                ],
                "assertions": [
                    {
                        "op": "=>",
                        "args": [
                            {"op": ">", "args": ["withdraw", 0]},
                            {"op": ">=", "args": ["balance", "withdraw"]},
                        ],
                    }
                ],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        assert "(=> (> withdraw 0) (>= balance withdraw))" in smt2

    def test_compilation_is_deterministic(self):
        policy_data = {
            "name": "det",
            "variables": [{"name": "x", "type": "int"}],
            "assertions": [{"op": ">", "args": ["x", 0]}],
        }
        a = compile_policy_to_smt2(JsonPolicy.model_validate(policy_data))
        b = compile_policy_to_smt2(JsonPolicy.model_validate(policy_data))
        assert a == b

    def test_unknown_operator_rejected(self):
        with pytest.raises(PolicyCompileError):
            compile_policy_to_smt2(
                JsonPolicy.model_validate(
                    {
                        "name": "bad_op",
                        "variables": [{"name": "x", "type": "int"}],
                        "assertions": [{"op": "bogus", "args": ["x", 0]}],
                    }
                )
            )

    def test_undeclared_variable_reference_rejected(self):
        with pytest.raises(PolicyCompileError):
            compile_policy_to_smt2(
                JsonPolicy.model_validate(
                    {
                        "name": "undeclared",
                        "variables": [{"name": "x", "type": "int"}],
                        "assertions": [{"op": ">", "args": ["y", 0]}],
                    }
                )
            )


# ---------------------------------------------------------------------------
# End-to-end Z3 evaluation (if z3-solver is installed)
# ---------------------------------------------------------------------------


class TestExamplePoliciesCompile:
    """Every shipped example JSON policy must parse, validate, and
    compile successfully so we can trust them as documentation.
    """

    def test_all_example_policies_compile(self):
        import json
        from pathlib import Path

        examples_dir = Path(__file__).resolve().parents[1] / "policies" / "examples"
        assert examples_dir.is_dir(), f"missing examples directory: {examples_dir}"
        example_files = sorted(examples_dir.glob("*.json"))
        assert example_files, "no example policies found"
        for path in example_files:
            with path.open() as f:
                data = json.load(f)
            policy = JsonPolicy.model_validate(data)
            smt2 = compile_policy_to_smt2(policy)
            assert smt2.strip(), f"{path.name}: compiled to empty SMT2"


@pytest.mark.skipif(not _Z3_AVAILABLE, reason="z3-solver not installed")
class TestPolicyCompilationRunsInZ3:
    def test_satisfiable_balance_conservation(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "balance_conservation",
                "variables": [
                    {"name": "alice", "type": "int"},
                    {"name": "bob", "type": "int"},
                    {"name": "total", "type": "int", "value": 100},
                ],
                "assertions": [
                    {"op": ">=", "args": ["alice", 0]},
                    {"op": ">=", "args": ["bob", 0]},
                    {"op": "==", "args": [{"op": "+", "args": ["alice", "bob"]}, "total"]},
                ],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        s = Solver()
        s.add(parse_smt2_string(smt2))
        assert s.check() == sat

    def test_unsatisfiable_contradiction(self):
        policy = JsonPolicy.model_validate(
            {
                "name": "contradiction",
                "variables": [{"name": "x", "type": "int"}],
                "assertions": [
                    {"op": ">", "args": ["x", 10]},
                    {"op": "<", "args": ["x", 5]},
                ],
            }
        )
        smt2 = compile_policy_to_smt2(policy)
        s = Solver()
        s.add(parse_smt2_string(smt2))
        assert s.check() == unsat
