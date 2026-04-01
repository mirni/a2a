"""Integration tests for the Identity system via the gateway.

Tests register_agent, verify_agent, submit_metrics, get_verified_claims,
get_agent_reputation, and tier enforcement through the /v1/execute endpoint.
"""

from __future__ import annotations

import pytest
from identity_src.crypto import AgentCrypto


class TestRegisterAgent:
    """Test agent registration via gateway."""

    @pytest.mark.asyncio
    async def test_register_agent_via_gateway(self, app, client, api_key):
        """register_agent should create a new identity and return a public key."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_agent",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["agent_id"] == "test-agent"
        assert len(result["public_key"]) == 64  # 32 bytes hex
        assert result["created_at"] > 0


class TestVerifyAgent:
    """Test agent signature verification via gateway."""

    @pytest.mark.asyncio
    async def test_verify_agent_via_gateway(self, app, client, api_key):
        """verify_agent should return valid=True for a correctly signed message."""
        priv, pub = AgentCrypto.generate_keypair()

        # Register agent with known public key
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_agent",
                "params": {"agent_id": "test-agent", "public_key": pub},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # Sign a message
        message = "prove identity"
        sig = AgentCrypto.sign(priv, message.encode())

        # Verify via gateway
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "verify_agent",
                "params": {
                    "agent_id": "test-agent",
                    "message": message,
                    "signature": sig,
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["valid"] is True


class TestSubmitMetrics:
    """Test metric submission via gateway."""

    @pytest.mark.asyncio
    async def test_submit_metrics_via_gateway(self, app, client, pro_api_key):
        """submit_metrics (pro tier) should create an attestation."""
        # Register agent first (free tier would work, but use pro key for both)
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_agent",
                "params": {"agent_id": "pro-agent"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200

        # Submit metrics
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "submit_metrics",
                "params": {
                    "agent_id": "pro-agent",
                    "metrics": {"sharpe_30d": 2.5, "max_drawdown_30d": 3.1},
                    "data_source": "self_reported",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["agent_id"] == "pro-agent"
        assert len(result["commitment_hashes"]) == 2
        assert result["data_source"] == "self_reported"
        assert len(result["signature"]) > 0

    @pytest.mark.asyncio
    async def test_submit_metrics_invalid_metric_returns_400(self, app, client, pro_api_key):
        """submit_metrics with invalid metric name should return 400, not 500."""
        await client.post(
            "/v1/execute",
            json={"tool": "register_agent", "params": {"agent_id": "pro-agent"}},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "submit_metrics",
                "params": {
                    "agent_id": "pro-agent",
                    "metrics": {"bogus_metric": 1.0},
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 400
        assert resp.json()["type"].endswith("/invalid-metric")

    @pytest.mark.asyncio
    async def test_submit_metrics_requires_pro_tier(self, app, client, api_key):
        """submit_metrics should fail for free-tier API keys."""
        # Register agent first
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_agent",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # Try submit_metrics with free tier key
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "submit_metrics",
                "params": {
                    "agent_id": "test-agent",
                    "metrics": {"sharpe_30d": 1.0},
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should be rejected: tier requirement not met
        assert resp.status_code == 403


class TestGetVerifiedClaims:
    """Test verified claims retrieval via gateway."""

    @pytest.mark.asyncio
    async def test_get_verified_claims_via_gateway(self, app, client, pro_api_key, api_key):
        """get_verified_claims should return claims created by submit_metrics."""
        # Register + submit metrics with pro key
        await client.post(
            "/v1/execute",
            json={"tool": "register_agent", "params": {"agent_id": "pro-agent"}},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        await client.post(
            "/v1/execute",
            json={
                "tool": "submit_metrics",
                "params": {
                    "agent_id": "pro-agent",
                    "metrics": {"sharpe_30d": 2.0, "p99_latency_ms": 50.0},
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )

        # Get claims — must use pro_api_key since agent_id is "pro-agent"
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_verified_claims",
                "params": {"agent_id": "pro-agent"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        claims = data["result"]["claims"]
        assert len(claims) == 2
        metric_names = {c["metric_name"] for c in claims}
        assert "sharpe_30d" in metric_names
        assert "p99_latency_ms" in metric_names


class TestGetReputation:
    """Test reputation retrieval via gateway."""

    @pytest.mark.asyncio
    async def test_get_reputation_via_gateway(self, app, client, api_key):
        """get_agent_reputation should return found=False when no reputation exists."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_agent_reputation",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["found"] is False

    @pytest.mark.asyncio
    async def test_get_reputation_after_compute(self, app, client, pro_api_key):
        """After submit_metrics + compute, get_agent_reputation should return data."""
        # Register and submit metrics
        await client.post(
            "/v1/execute",
            json={"tool": "register_agent", "params": {"agent_id": "pro-agent"}},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        await client.post(
            "/v1/execute",
            json={
                "tool": "submit_metrics",
                "params": {
                    "agent_id": "pro-agent",
                    "metrics": {"sharpe_30d": 3.0},
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )

        # Compute reputation directly via the API (no gateway endpoint for compute)
        identity_api = app.state.ctx.identity_api
        await identity_api.compute_reputation("pro-agent")

        # Now fetch via gateway — must use pro_api_key since agent_id is "pro-agent"
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_agent_reputation",
                "params": {"agent_id": "pro-agent"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert result["found"] is True
        assert result["composite_score"] > 0
        assert result["confidence"] > 0
