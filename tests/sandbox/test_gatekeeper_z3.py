"""Sandbox parity: Gatekeeper Z3 verification (13-release regression).

The external audit has flagged Z3 as broken on sandbox for 13 consecutive
releases. This test submits SAT and UNSAT Z3 expressions to the live
sandbox and verifies that jobs complete with the correct result.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

# Z3 is broken on sandbox (13-release regression). These tests document the
# expected behaviour and will xpass once the postinst fixes in this PR are
# deployed. Remove the xfail marker after the first green sandbox deploy.
_z3_xfail = pytest.mark.xfail(
    reason="Z3 broken on sandbox — postinst fixes not yet deployed",
    strict=False,
)


class TestSandboxGatekeeperZ3:
    @_z3_xfail
    async def test_z3_sat_job_completes(self, sandbox_client, admin_key):
        """Submit a SAT Z3 expression — must return status=completed, result=satisfied."""
        resp = await sandbox_client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "audit-admin",
                "properties": [
                    {
                        "name": "smoke_sat",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (> x 0))",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 201, f"Submit failed: {resp.text}"
        body = resp.json()
        assert body["status"] == "completed", (
            f"Z3 job should complete, got status={body.get('status')}, result={body.get('result')}"
        )
        assert body["result"] == "satisfied"

    @_z3_xfail
    async def test_z3_unsat_job_completes(self, sandbox_client, admin_key):
        """Submit an UNSAT Z3 expression — must return status=completed, result=violated."""
        resp = await sandbox_client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "audit-admin",
                "properties": [
                    {
                        "name": "smoke_unsat",
                        "language": "z3_smt2",
                        "expression": "(declare-const x Int)\n(assert (and (> x 0) (< x 0)))",
                    }
                ],
            },
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 201, f"Submit failed: {resp.text}"
        body = resp.json()
        assert body["status"] == "completed", (
            f"Z3 job should complete, got status={body.get('status')}, result={body.get('result')}"
        )
        assert body["result"] == "violated"
