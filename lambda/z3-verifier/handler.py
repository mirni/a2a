"""AWS Lambda handler for Z3 SMT verification jobs."""

import hashlib
import json
import logging
import time

from z3 import Solver, parse_smt2_string, sat, unsat

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Safety limits
MAX_PROPERTIES = 100
MAX_EXPRESSION_LENGTH = 1_000_000  # 1MB
PER_PROPERTY_TIMEOUT_MS = 60_000  # 60s hard cap

# Result priority: error > violated > unknown > satisfied
_RESULT_PRIORITY = {"satisfied": 0, "unknown": 1, "violated": 2, "error": 3}


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
        "result": "satisfied" | "violated" | "unknown" | "error",
        "property_results": [...],
        "proof_data": "...",
        "proof_hash": "...",
        "duration_ms": 1234
    }
    """
    start = time.monotonic()

    # Input validation
    if not isinstance(event, dict):
        return {"status": "error", "result": "error", "detail": "event must be a JSON object"}

    job_id = event.get("job_id", "unknown")
    properties = event.get("properties", [])
    timeout_ms = event.get("timeout_seconds", 300) * 1000

    if not isinstance(properties, list):
        return {"job_id": job_id, "status": "error", "result": "error", "detail": "properties must be a list"}

    if len(properties) > MAX_PROPERTIES:
        return {
            "job_id": job_id,
            "status": "error",
            "result": "error",
            "detail": f"Too many properties: {len(properties)} (max {MAX_PROPERTIES})",
        }

    property_results = []
    overall_result = "satisfied"

    for prop in properties:
        name = prop.get("name", "unnamed") if isinstance(prop, dict) else "unnamed"
        expression = prop.get("expression", "") if isinstance(prop, dict) else ""

        # Validate expression size
        if len(expression) > MAX_EXPRESSION_LENGTH:
            property_results.append(
                {
                    "name": name,
                    "result": "error",
                    "reason": f"Expression too large: {len(expression)} bytes (max {MAX_EXPRESSION_LENGTH})",
                }
            )
            overall_result = _higher_priority(overall_result, "error")
            continue

        try:
            solver = Solver()
            solver.set("timeout", min(timeout_ms, PER_PROPERTY_TIMEOUT_MS))

            assertions = parse_smt2_string(expression)
            solver.add(assertions)

            check = solver.check()

            if check == sat:
                model_str = str(solver.model())
                # Truncate large models
                if len(model_str) > 10_000:
                    model_str = model_str[:10_000] + "... (truncated)"
                property_results.append(
                    {
                        "name": name,
                        "result": "satisfied",
                        "model": model_str,
                    }
                )
            elif check == unsat:
                property_results.append(
                    {
                        "name": name,
                        "result": "violated",
                        "reason": "unsatisfiable",
                    }
                )
                overall_result = _higher_priority(overall_result, "violated")
            else:
                property_results.append(
                    {
                        "name": name,
                        "result": "unknown",
                        "reason": str(solver.reason_unknown()),
                    }
                )
                overall_result = _higher_priority(overall_result, "unknown")

        except Exception as e:
            logger.error("Z3 error for property '%s' in job %s: %s", name, job_id, e)
            property_results.append(
                {
                    "name": name,
                    "result": "error",
                    "reason": str(e),
                }
            )
            overall_result = _higher_priority(overall_result, "error")

    duration_ms = int((time.monotonic() - start) * 1000)

    # Build deterministic proof data blob (no timestamp — reproducible hash)
    proof_blob = json.dumps(
        {
            "job_id": job_id,
            "result": overall_result,
            "property_results": property_results,
        },
        sort_keys=True,
    )
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


def _higher_priority(current: str, new: str) -> str:
    """Return the higher-priority result (error > violated > unknown > satisfied)."""
    if _RESULT_PRIORITY.get(new, 0) > _RESULT_PRIORITY.get(current, 0):
        return new
    return current
