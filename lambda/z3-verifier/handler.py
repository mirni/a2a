"""AWS Lambda handler for Z3 SMT verification jobs."""

import hashlib
import json
import time
import traceback

from z3 import Solver, parse_smt2_string, sat, unknown, unsat


def lambda_handler(event, context):
    """Process a Z3 verification job.

    Input event:
    {
        "job_id": "vj-abc123",
        "properties": [
            {"name": "balance_conservation", "language": "z3_smt2",
             "expression": "(declare-const x Int)\\n(assert (> x 0))"}
        ],
        "timeout_seconds": 300
    }

    Output:
    {
        "job_id": "vj-abc123",
        "status": "completed",
        "result": "satisfied" | "violated" | "unknown",
        "property_results": [...],
        "proof_data": "...",
        "proof_hash": "...",
        "duration_ms": 1234
    }
    """
    start = time.monotonic()
    job_id = event.get("job_id", "unknown")
    properties = event.get("properties", [])
    timeout_ms = event.get("timeout_seconds", 300) * 1000

    property_results = []
    overall_result = "satisfied"

    for prop in properties:
        name = prop.get("name", "unnamed")
        expression = prop.get("expression", "")

        try:
            solver = Solver()
            solver.set("timeout", min(timeout_ms, 60000))  # Per-property cap

            assertions = parse_smt2_string(expression)
            solver.add(assertions)

            check = solver.check()

            if check == sat:
                model_str = str(solver.model())
                property_results.append({
                    "name": name,
                    "result": "satisfied",
                    "model": model_str,
                })
            elif check == unsat:
                property_results.append({
                    "name": name,
                    "result": "violated",
                    "reason": "unsatisfiable",
                    "proof": str(solver.proof()) if solver.proof() else None,
                })
                overall_result = "violated"
            else:
                property_results.append({
                    "name": name,
                    "result": "unknown",
                    "reason": str(solver.reason_unknown()),
                })
                if overall_result == "satisfied":
                    overall_result = "unknown"

        except Exception as e:
            property_results.append({
                "name": name,
                "result": "error",
                "reason": str(e),
                "traceback": traceback.format_exc(),
            })
            overall_result = "error"

    duration_ms = int((time.monotonic() - start) * 1000)

    # Build proof data blob for hashing
    proof_blob = json.dumps({
        "job_id": job_id,
        "result": overall_result,
        "property_results": property_results,
        "timestamp": time.time(),
    }, sort_keys=True)
    proof_hash = hashlib.sha3_256(proof_blob.encode()).hexdigest()

    return {
        "job_id": job_id,
        "status": "completed",
        "result": overall_result,
        "property_results": property_results,
        "proof_data": proof_blob,
        "proof_hash": proof_hash,
        "duration_ms": duration_ms,
    }
