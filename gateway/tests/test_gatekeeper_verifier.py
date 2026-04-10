"""Tests for VerifierClient wiring in gateway lifespan.

Verifies that when VERIFIER_AUTH_MODE=mock is set, submitted verification
jobs are executed immediately (status=completed, not stuck in pending).
"""

from __future__ import annotations

import os
import sys

import httpx
import pytest

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import gateway.src.bootstrap  # noqa: F401, I001
from gateway.src.app import create_app
from gateway.src.lifespan import lifespan
from gateway.src.routes.sse import SSEConfig

_VALID_PROPERTY = {
    "name": "balance_check",
    "expression": "(declare-const x Int)\n(assert (> x 0))",
}

z3_available = False
try:
    import z3  # noqa: F401

    z3_available = True
except ImportError:
    pass

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not z3_available, reason="z3-solver not installed"),
]


@pytest.fixture
async def mock_verifier_app(tmp_path, monkeypatch):
    """Create a FastAPI app with VERIFIER_AUTH_MODE=mock."""
    data_dir = str(tmp_path)
    monkeypatch.setenv("A2A_DATA_DIR", data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    monkeypatch.setenv("IDENTITY_DSN", f"sqlite:///{data_dir}/identity.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db")
    monkeypatch.setenv("DISPUTE_DSN", f"sqlite:///{data_dir}/disputes.db")
    monkeypatch.setenv("MESSAGING_DSN", f"sqlite:///{data_dir}/messaging.db")
    monkeypatch.setenv("VERIFIER_AUTH_MODE", "mock")

    application = create_app()
    application.state.sse_config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.3,
    )

    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    yield application
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def mock_client(mock_verifier_app):
    transport = httpx.ASGITransport(app=mock_verifier_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def mock_pro_api_key(mock_verifier_app, mock_client):
    ctx = mock_verifier_app.state.ctx
    await ctx.tracker.wallet.create("pro-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("pro-agent", tier="pro")
    return key_info["key"]


class TestVerifierWiring:
    async def test_mock_verifier_completes_job(self, mock_client, mock_pro_api_key):
        """With VERIFIER_AUTH_MODE=mock, submitted jobs should complete immediately."""
        r = await mock_client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {mock_pro_api_key}"},
        )
        assert r.status_code == 201
        job_id = r.json()["job_id"]

        # Job should be completed (not pending) because mock verifier runs inline
        resp = await mock_client.get(
            f"/v1/gatekeeper/jobs/{job_id}",
            headers={"Authorization": f"Bearer {mock_pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] in ("satisfied", "violated", "unknown", "error")

    async def test_mock_verifier_creates_proof(self, mock_client, mock_pro_api_key):
        """Completed verification job should produce a proof artifact."""
        r = await mock_client.post(
            "/v1/gatekeeper/jobs",
            json={"agent_id": "pro-agent", "properties": [_VALID_PROPERTY]},
            headers={"Authorization": f"Bearer {mock_pro_api_key}"},
        )
        assert r.status_code == 201
        job_id = r.json()["job_id"]

        resp = await mock_client.get(
            f"/v1/gatekeeper/jobs/{job_id}",
            headers={"Authorization": f"Bearer {mock_pro_api_key}"},
        )
        data = resp.json()
        assert data["status"] == "completed"
        proof_id = data.get("proof_artifact_id")
        assert proof_id is not None

        # Retrieve the proof
        proof_resp = await mock_client.get(
            f"/v1/gatekeeper/proofs/{proof_id}",
            headers={"Authorization": f"Bearer {mock_pro_api_key}"},
        )
        assert proof_resp.status_code == 200
        proof = proof_resp.json()
        assert proof["proof_hash"]
        assert len(proof["property_results"]) > 0

    async def test_gatekeeper_api_has_verifier(self, mock_verifier_app):
        """GatekeeperAPI should have a verifier attached when mock mode is active."""
        ctx = mock_verifier_app.state.ctx
        assert ctx.gatekeeper_api is not None
        assert ctx.gatekeeper_api.verifier is not None
