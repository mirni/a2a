"""Sandbox parity: Gatekeeper Z3 verification (13-release regression).

The external audit has flagged Z3 as broken on sandbox for 13 consecutive
releases. This test submits SAT and UNSAT Z3 expressions to the live
sandbox and verifies that jobs complete with the correct result.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestSandboxGatekeeperZ3:
    async def test_z3_sat_job_completes(self, sandbox_client, pro_key):
        """Submit a SAT Z3 expression — must return status=completed, result=satisfied."""
        resp = await sandbox_client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "audit-pro",
                "properties": [
                    {
                        "name": "smoke_sat",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (> x 0))",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {pro_key}"},
        )
        assert resp.status_code == 201, f"Submit failed: {resp.text}"
        body = resp.json()
        assert body["status"] == "completed", (
            f"Z3 job should complete, got status={body.get('status')}, result={body.get('result')}"
        )
        assert body["result"] == "satisfied"

    async def test_z3_unsat_job_completes(self, sandbox_client, pro_key):
        """Submit an UNSAT Z3 expression — must return status=completed, result=violated."""
        resp = await sandbox_client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "audit-pro",
                "properties": [
                    {
                        "name": "smoke_unsat",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (and (> x 0) (< x 0)))",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {pro_key}"},
        )
        assert resp.status_code == 201, f"Submit failed: {resp.text}"
        body = resp.json()
        assert body["status"] == "completed", (
            f"Z3 job should complete, got status={body.get('status')}, result={body.get('result')}"
        )
        assert body["result"] == "violated"
