"""Tests for gateway trust <-> marketplace integration.

Verifies that the gateway wires the TrustAPI into the Marketplace as a
trust_provider, so marketplace tools return live trust scores.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _register_trust_server(app, server_id: str, name: str) -> None:
    """Register a server in the trust system and give it probe data for a score."""
    from trust_src.models import ProbeResult, SecurityScan
    import time

    trust_api = app.state.ctx.trust_api
    storage = trust_api.storage

    await trust_api.register_server(
        name=name,
        url=f"https://{name}.example.com",
        server_id=server_id,
    )

    # Insert probe results so a trust score can be computed
    ts = time.time()
    probe = ProbeResult(
        server_id=server_id,
        timestamp=ts,
        latency_ms=50.0,
        status_code=200,
        tools_count=5,
        tools_documented=4,
    )
    await storage.store_probe_result(probe)

    scan = SecurityScan(
        server_id=server_id,
        timestamp=ts,
        tls_enabled=True,
        auth_required=True,
        input_validation_score=80.0,
        cve_count=0,
    )
    await storage.store_security_scan(scan)


async def _register_marketplace_service(
    client, api_key, provider_id: str, name: str, category: str = "data"
) -> dict:
    """Register a service in the marketplace through the gateway.

    Uses the provided api_key which must be pro-tier (register_service requires pro).
    """
    resp = await client.post(
        "/execute",
        json={
            "tool": "register_service",
            "params": {
                "provider_id": provider_id,
                "name": name,
                "description": f"Service by {provider_id}",
                "category": category,
                "tags": ["test"],
                "endpoint": f"https://{provider_id}.example.com",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


# ---------------------------------------------------------------------------
# Tests: marketplace tools include trust scores
# ---------------------------------------------------------------------------


class TestGatewayTrustMarketplace:
    """Gateway marketplace tools should return trust scores from live TrustAPI."""

    @pytest.mark.asyncio
    async def test_search_returns_trust_score(self, app, client, pro_api_key, api_key):
        """search_services through gateway should include trust_score in results."""
        # Register a server in trust system
        await _register_trust_server(app, server_id="srv-1", name="Trusted Server")

        # Register a marketplace service with same provider_id (requires pro tier)
        await _register_marketplace_service(
            client, pro_api_key, provider_id="srv-1", name="Trusted Service"
        )

        # Search (free tier) and verify trust_score is present
        resp = await client.post(
            "/execute",
            json={"tool": "search_services", "params": {"query": "Trusted"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        services = data["result"]["services"]
        assert len(services) == 1
        assert "trust_score" in services[0]
        assert services[0]["trust_score"] is not None
        assert isinstance(services[0]["trust_score"], (int, float))
        assert 0 <= services[0]["trust_score"] <= 100

    @pytest.mark.asyncio
    async def test_search_without_trust_data_returns_none(
        self, app, client, pro_api_key, api_key
    ):
        """Services with provider_id not in trust system should get trust_score=None."""
        await _register_marketplace_service(
            client, pro_api_key, provider_id="no-trust-data", name="Unscored Service"
        )

        resp = await client.post(
            "/execute",
            json={"tool": "search_services", "params": {"query": "Unscored"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        services = resp.json()["result"]["services"]
        assert len(services) == 1
        assert services[0]["trust_score"] is None

    @pytest.mark.asyncio
    async def test_best_match_uses_live_trust(self, app, client, pro_api_key, api_key):
        """best_match through gateway should use live trust data for ranking."""
        # Create two trust-registered servers with different trust profiles
        await _register_trust_server(app, server_id="high-t", name="HighTrust")
        await _register_trust_server(app, server_id="low-t", name="LowTrust")

        # Give low-t a bad probe so its score is lower
        from trust_src.models import ProbeResult
        import time

        low_probe = ProbeResult(
            server_id="low-t",
            timestamp=time.time(),
            latency_ms=5000.0,
            status_code=500,
            error="timeout",
            tools_count=1,
            tools_documented=0,
        )
        await app.state.ctx.trust_api.storage.store_probe_result(low_probe)

        # Register marketplace services (requires pro tier)
        await _register_marketplace_service(
            client, pro_api_key, provider_id="high-t", name="Premium Data Service"
        )
        await _register_marketplace_service(
            client, pro_api_key, provider_id="low-t", name="Budget Data Service"
        )

        # best_match (free tier) with prefer=trust
        resp = await client.post(
            "/execute",
            json={
                "tool": "best_match",
                "params": {
                    "query": "Data Service",
                    "prefer": "trust",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        matches = resp.json()["result"]["matches"]
        assert len(matches) >= 2

        # The match with the higher trust score should come first
        # Both have "Data Service" in name, so text relevance is same
        # The one with good probes (high-t) should rank higher
        first_service = matches[0]["service"]
        assert first_service["name"] == "Premium Data Service"


class TestGatewayTrustAdapterWired:
    """Verify the trust adapter is actually wired into the marketplace."""

    @pytest.mark.asyncio
    async def test_marketplace_has_trust_provider(self, app):
        """After lifespan, marketplace should have a trust_provider set."""
        marketplace = app.state.ctx.marketplace
        assert marketplace._trust_provider is not None
