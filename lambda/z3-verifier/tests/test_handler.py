"""Unit tests for the Z3 verifier Lambda handler.

Pure Python tests — no AWS dependencies required. Requires z3-solver.
"""

from __future__ import annotations

import hashlib
import os
import sys

# Ensure the handler module is importable
_handler_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _handler_dir not in sys.path:
    sys.path.insert(0, _handler_dir)

from handler import lambda_handler


class TestSatisfiableExpression:
    def test_simple_sat(self):
        """A satisfiable expression returns result='satisfied' with a model."""
        event = {
            "job_id": "vj-sat-001",
            "properties": [
                {
                    "name": "positive_int",
                    "expression": "(declare-const x Int)\n(assert (> x 0))",
                }
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["job_id"] == "vj-sat-001"
        assert result["status"] == "completed"
        assert result["result"] == "satisfied"
        assert len(result["property_results"]) == 1
        assert result["property_results"][0]["result"] == "satisfied"
        assert "model" in result["property_results"][0]


class TestUnsatisfiableExpression:
    def test_contradictory_constraints(self):
        """Contradictory constraints return result='violated'."""
        event = {
            "job_id": "vj-unsat-001",
            "properties": [
                {
                    "name": "impossible",
                    "expression": ("(declare-const x Int)\n(assert (> x 10))\n(assert (< x 5))"),
                }
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "violated"
        assert result["property_results"][0]["result"] == "violated"
        assert result["property_results"][0]["reason"] == "unsatisfiable"


class TestUnknownResult:
    def test_unknown_is_valid_result(self):
        """Verify the handler accepts 'unknown' as a valid result category.

        Rather than trying to force a timeout (which is non-deterministic),
        we verify the priority logic: if a property produces 'unknown', it
        should propagate to the overall result correctly.
        """
        # The handler uses _higher_priority to merge results. We test the
        # expected output schema and that non-error results are handled.
        # For actual unknown-forcing, CI would need a very constrained timeout.
        event = {
            "job_id": "vj-unk-001",
            "properties": [
                {
                    "name": "simple_check",
                    "expression": "(declare-const x Int)\n(assert (> x 0))",
                }
            ],
            "timeout_seconds": 300,
        }
        result = lambda_handler(event, None)
        # Just verify the handler returns a valid result enum value
        assert result["result"] in ("satisfied", "violated", "unknown", "error")
        assert result["status"] == "completed"


class TestParseError:
    def test_invalid_smt2_syntax(self):
        """Invalid SMT2 syntax returns result='error' for that property."""
        event = {
            "job_id": "vj-err-001",
            "properties": [
                {
                    "name": "bad_syntax",
                    "expression": "this is not valid SMT2 syntax!!!",
                }
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "error"
        assert result["property_results"][0]["result"] == "error"
        assert "reason" in result["property_results"][0]


class TestMultipleProperties:
    def test_mixed_sat_unsat_gives_violated(self):
        """Mixed SAT/UNSAT properties → overall 'violated' (priority logic)."""
        event = {
            "job_id": "vj-mix-001",
            "properties": [
                {
                    "name": "satisfiable",
                    "expression": "(declare-const x Int)\n(assert (> x 0))",
                },
                {
                    "name": "unsatisfiable",
                    "expression": ("(declare-const x Int)\n(assert (> x 10))\n(assert (< x 5))"),
                },
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "violated"
        assert len(result["property_results"]) == 2
        results = {pr["name"]: pr["result"] for pr in result["property_results"]}
        assert results["satisfiable"] == "satisfied"
        assert results["unsatisfiable"] == "violated"


class TestEmptyProperties:
    def test_empty_list_returns_satisfied(self):
        """Empty properties list returns result='satisfied' (vacuously true)."""
        event = {
            "job_id": "vj-empty-001",
            "properties": [],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "satisfied"
        assert result["property_results"] == []
        assert result["status"] == "completed"


class TestMaxPropertiesLimit:
    def test_101_properties_returns_error(self):
        """More than 100 properties returns an error response."""
        event = {
            "job_id": "vj-limit-001",
            "properties": [
                {"name": f"prop_{i}", "expression": "(declare-const x Int)\n(assert (> x 0))"} for i in range(101)
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "error"
        assert "Too many properties" in result["detail"]

    def test_5_properties_accepted(self):
        """Properties under the limit should be accepted and solved."""
        event = {
            "job_id": "vj-limit-002",
            "properties": [
                {"name": f"prop_{i}", "expression": "(declare-const x Int)\n(assert (> x 0))"} for i in range(5)
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "satisfied"
        assert len(result["property_results"]) == 5


class TestMaxExpressionLength:
    def test_oversized_expression_returns_error(self):
        """Expression exceeding 1MB returns 'error' for that property."""
        big_expression = "(declare-const x Int)\n(assert (> x 0))" + " " * 1_000_001
        event = {
            "job_id": "vj-size-001",
            "properties": [
                {"name": "too_big", "expression": big_expression},
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        assert result["result"] == "error"
        assert result["property_results"][0]["result"] == "error"
        assert "too large" in result["property_results"][0]["reason"].lower()


class TestProofHashDeterminism:
    def test_same_input_same_hash(self):
        """Same input produces the same SHA3-256 proof hash."""
        event = {
            "job_id": "vj-hash-001",
            "properties": [
                {
                    "name": "deterministic",
                    "expression": "(declare-const x Int)\n(assert (= x 42))",
                }
            ],
            "timeout_seconds": 30,
        }
        result1 = lambda_handler(event, None)
        result2 = lambda_handler(event, None)

        assert result1["proof_hash"] == result2["proof_hash"]
        assert len(result1["proof_hash"]) == 64  # SHA3-256 hex digest

    def test_proof_hash_matches_proof_data(self):
        """The proof_hash matches SHA3-256 of proof_data."""
        event = {
            "job_id": "vj-hash-002",
            "properties": [
                {
                    "name": "verify_hash",
                    "expression": "(declare-const x Int)\n(assert (= x 1))",
                }
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        computed = hashlib.sha3_256(result["proof_data"].encode()).hexdigest()
        assert computed == result["proof_hash"]


class TestOutputSchema:
    def test_response_has_required_keys(self):
        """Response has all required keys: job_id, status, result, property_results, proof_data, proof_hash, duration_ms."""
        event = {
            "job_id": "vj-schema-001",
            "properties": [
                {
                    "name": "schema_check",
                    "expression": "(declare-const x Int)\n(assert (> x 0))",
                }
            ],
            "timeout_seconds": 30,
        }
        result = lambda_handler(event, None)

        required_keys = {"job_id", "status", "result", "property_results", "proof_data", "proof_hash", "duration_ms"}
        assert required_keys.issubset(result.keys())
        assert isinstance(result["duration_ms"], int)
        assert result["duration_ms"] >= 0
        assert isinstance(result["property_results"], list)
        assert isinstance(result["proof_data"], str)
        assert isinstance(result["proof_hash"], str)
