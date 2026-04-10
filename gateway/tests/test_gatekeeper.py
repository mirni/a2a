"""Gateway-level tests for the Formal Gatekeeper verification endpoints."""

import pytest

_VALID_PROPERTY = {
    "name": "balance_check",
    "expression": "(declare-const x Int)\n(assert (> x 0))",
}


# ---------------------------------------------------------------------------
# Submit Verification
# ---------------------------------------------------------------------------


class TestSubmitVerification:
    @pytest.mark.asyncio
    async def test_submit_job(self, client, pro_api_key):
        """Submit a valid SAT job. With the mock verifier wired up
        (v1.2.2 T-1 defensive default), the job executes in-process
        and reports a terminal status rather than ``pending``.
        """
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "pro-agent",
                "properties": [_VALID_PROPERTY],
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["job_id"].startswith("vj-")
        assert data["status"] in {"pending", "completed", "failed", "timeout"}
        assert "cost" in data

    @pytest.mark.asyncio
    async def test_submit_extra_fields_rejected(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "pro-agent",
                "properties": [_VALID_PROPERTY],
                "bogus": "field",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_empty_properties_rejected(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": []},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_ownership_check(self, client, pro_api_key):
        """Pro agent cannot submit for a different agent_id."""
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "other-agent",
                "properties": [_VALID_PROPERTY],
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_free_tier_rejected(self, client, api_key):
        """Free-tier agent cannot use gatekeeper tools."""
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "test-agent",
                "properties": [_VALID_PROPERTY],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_submit_idempotency(self, client, pro_api_key):
        body = {
            "agent_id": "pro-agent",
            "properties": [_VALID_PROPERTY],
            "idempotency_key": "idem-gw-001",
        }
        r1 = await client.post(
            "/v1/gatekeeper/jobs",
            json=body,
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert r1.status_code == 201
        job_id = r1.json()["job_id"]

        r2 = await client.post(
            "/v1/gatekeeper/jobs",
            json=body,
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        # Idempotent: returns same job
        assert r2.status_code == 201
        assert r2.json()["job_id"] == job_id

    @pytest.mark.asyncio
    async def test_submit_with_webhook(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "pro-agent",
                "properties": [_VALID_PROPERTY],
                "webhook_url": "https://example.com/hook",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_submit_http_webhook_rejected(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "pro-agent",
                "properties": [_VALID_PROPERTY],
                "webhook_url": "http://evil.example.com/hook",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        # Model validator rejects non-HTTPS — surfaced as product exception
        assert resp.status_code in (400, 422, 500)

    @pytest.mark.asyncio
    async def test_submit_timeout_validation(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs",
            json={
                "agent_id": "pro-agent",
                "properties": [_VALID_PROPERTY],
                "timeout_seconds": 5,  # Below minimum of 10
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Get Verification Status
# ---------------------------------------------------------------------------


class TestGetVerificationStatus:
    @pytest.mark.asyncio
    async def test_get_status(self, client, pro_api_key):
        r = await client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        job_id = r.json()["job_id"]

        resp = await client.get(
            f"/v1/gatekeeper/jobs/{job_id}",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in {"pending", "completed", "failed", "timeout"}
        assert data["agent_id"] == "pro-agent"

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, client, pro_api_key):
        resp = await client.get(
            "/v1/gatekeeper/jobs/vj-nonexistent",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_status_idor_blocked(self, client, app, pro_api_key):
        """Another pro agent cannot view this agent's job."""
        # pro-agent creates a job
        r = await client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        job_id = r.json()["job_id"]

        # Create a second pro agent
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-agent-2", initial_balance=5000.0, signup_bonus=False)
        key2 = await ctx.key_manager.create_key("pro-agent-2", tier="pro")

        # pro-agent-2 tries to read it
        resp = await client.get(
            f"/v1/gatekeeper/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key2['key']}"},
        )
        assert resp.status_code in (403, 400)


# ---------------------------------------------------------------------------
# List Verification Jobs
# ---------------------------------------------------------------------------


class TestListVerificationJobs:
    @pytest.mark.asyncio
    async def test_list_jobs(self, client, pro_api_key):
        for _ in range(2):
            await client.post(
                "/v1/gatekeeper/jobs",
                json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
                headers={"Authorization": f"Bearer {pro_api_key}"},
            )

        resp = await client.get(
            "/v1/gatekeeper/jobs?agent_id=pro-agent",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        assert len(data["jobs"]) >= 2

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client, pro_api_key):
        resp = await client.get(
            "/v1/gatekeeper/jobs?agent_id=pro-agent",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_list_jobs_ownership(self, client, pro_api_key):
        """Cannot list another agent's jobs."""
        resp = await client.get(
            "/v1/gatekeeper/jobs?agent_id=other-agent",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_jobs_with_limit(self, client, pro_api_key):
        resp = await client.get(
            "/v1/gatekeeper/jobs?agent_id=pro-agent&limit=5",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_jobs_invalid_limit(self, client, pro_api_key):
        resp = await client.get(
            "/v1/gatekeeper/jobs?agent_id=pro-agent&limit=0",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Cancel Verification
# ---------------------------------------------------------------------------


class TestCancelVerification:
    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, client, app, pro_api_key):
        """Cancel a pending job. v1.2.2 defensive default wires a
        synchronous mock verifier, so we temporarily clear the
        verifier to leave the job in ``pending`` state.
        """
        ctx = app.state.ctx
        original = ctx.gatekeeper_api.verifier
        ctx.gatekeeper_api.verifier = None
        try:
            r = await client.post(
                "/v1/gatekeeper/jobs",
                json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
                headers={"Authorization": f"Bearer {pro_api_key}"},
            )
            job_id = r.json()["job_id"]

            resp = await client.post(
                f"/v1/gatekeeper/jobs/{job_id}/cancel",
                headers={"Authorization": f"Bearer {pro_api_key}"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"
        finally:
            ctx.gatekeeper_api.verifier = original

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self, client, pro_api_key):
        r = await client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        job_id = r.json()["job_id"]

        await client.post(
            f"/v1/gatekeeper/jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )

        resp = await client.post(
            f"/v1/gatekeeper/jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_not_found(self, client, pro_api_key):
        resp = await client.post(
            "/v1/gatekeeper/jobs/vj-nonexistent/cancel",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_idor_blocked(self, client, app, pro_api_key):
        r = await client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        job_id = r.json()["job_id"]

        ctx = app.state.ctx
        await ctx.tracker.wallet.create("pro-agent-3", initial_balance=5000.0, signup_bonus=False)
        key3 = await ctx.key_manager.create_key("pro-agent-3", tier="pro")

        resp = await client.post(
            f"/v1/gatekeeper/jobs/{job_id}/cancel",
            headers={"Authorization": f"Bearer {key3['key']}"},
        )
        assert resp.status_code in (403, 400)


# ---------------------------------------------------------------------------
# Proofs
# ---------------------------------------------------------------------------


class TestGetProof:
    @pytest.mark.asyncio
    async def test_get_proof_not_found(self, client, pro_api_key):
        resp = await client.get(
            "/v1/gatekeeper/proofs/pf-nonexistent",
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 404


class TestVerifyProof:
    @pytest.mark.asyncio
    async def test_verify_proof_not_found(self, client, api_key):
        """verify_proof is free tier — test with free key."""
        resp = await client.post(
            "/v1/gatekeeper/proofs/verify",
            json={"proof_hash": "nonexistent-hash"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_verify_proof_extra_fields(self, client, api_key):
        resp = await client.post(
            "/v1/gatekeeper/proofs/verify",
            json={"proof_hash": "abc", "extra": "bad"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_verify_proof_missing_hash(self, client, api_key):
        resp = await client.post(
            "/v1/gatekeeper/proofs/verify",
            json={},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422
