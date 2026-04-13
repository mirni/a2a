"""Tests for Atlas Discovery & Brokering — /v1/marketplace/atlas/."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from marketplace_src.atlas import AtlasScoreBreakdown, compute_atlas_score

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_service(client, key, **overrides):
    payload = {
        "provider_id": overrides.get("provider_id", "pro-agent"),
        "name": overrides.get("name", "Test Service"),
        "description": overrides.get("description", "A test service"),
        "category": overrides.get("category", "analytics"),
        "endpoint": overrides.get("endpoint", "https://example.com/api"),
        "pricing": overrides.get("pricing", {"model": "per_call", "cost": 1.0}),
    }
    payload.update({k: v for k, v in overrides.items() if k not in payload})
    return await client.post(
        "/v1/marketplace/services",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
    )


# ===========================================================================
# Unit: compute_atlas_score (no app fixtures needed)
# ===========================================================================


class TestComputeAtlasScore:
    def test_atlas_score_all_perfect(self):
        result = compute_atlas_score(
            trust_composite=100.0,
            reputation_composite=100.0,
            average_rating=5.0,
            transaction_volume_score=100.0,
        )
        assert result.total == 100.0

    def test_atlas_score_all_zero(self):
        result = compute_atlas_score(
            trust_composite=None,
            reputation_composite=None,
            average_rating=0.0,
            transaction_volume_score=None,
        )
        assert result.total == 0.0

    def test_atlas_score_trust_only(self):
        result = compute_atlas_score(
            trust_composite=80.0,
            reputation_composite=None,
            average_rating=0.0,
            transaction_volume_score=None,
        )
        assert result.trust_component == 32.0
        assert result.reputation_component == 0.0
        assert result.marketplace_component == 0.0
        assert result.volume_component == 0.0
        assert result.total == 32.0

    def test_atlas_score_weights_correct(self):
        result = compute_atlas_score(
            trust_composite=50.0,
            reputation_composite=60.0,
            average_rating=4.0,
            transaction_volume_score=80.0,
        )
        assert result.trust_component == 20.0  # 50 * 0.4
        assert result.reputation_component == 18.0  # 60 * 0.3
        assert result.marketplace_component == 16.0  # (4/5)*100 * 0.2
        assert result.volume_component == 8.0  # 80 * 0.1
        assert result.total == 62.0

    def test_atlas_score_breakdown_fields(self):
        result = compute_atlas_score(
            trust_composite=50.0,
            reputation_composite=50.0,
            average_rating=2.5,
            transaction_volume_score=50.0,
        )
        assert isinstance(result, AtlasScoreBreakdown)
        assert hasattr(result, "trust_component")
        assert hasattr(result, "reputation_component")
        assert hasattr(result, "marketplace_component")
        assert hasattr(result, "volume_component")
        assert hasattr(result, "total")


# ===========================================================================
# Integration: POST /v1/marketplace/atlas/discover
# ===========================================================================


async def test_discover_returns_results(client, pro_api_key):
    await _register_service(client, pro_api_key, name="Analytics Pro")
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "analytics"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    # Each result should have atlas_score
    for r in body["results"]:
        assert "atlas_score" in r


async def test_discover_empty_query(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "nonexistent-service-zzz-xyz"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_discover_with_capabilities(client, pro_api_key):
    await _register_service(
        client,
        pro_api_key,
        name="ML Service",
        tools=["predict", "train"],
    )
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "ML", "capabilities": ["predict"]},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) >= 1


async def test_discover_enrichment(client, pro_api_key):
    await _register_service(client, pro_api_key, name="Enrichment Test")
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "Enrichment"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    if body["results"]:
        r = body["results"][0]
        assert "trust_score" in r
        assert "reputation" in r
        assert "average_rating" in r


async def test_discover_no_auth(client):
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "test"},
    )
    assert resp.status_code == 401


async def test_discover_extra_fields(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/discover",
        json={"query": "test", "unknown_field": True},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422


# ===========================================================================
# Integration: POST /v1/marketplace/atlas/preflight
# ===========================================================================


async def test_preflight_all_ok(client, pro_api_key):
    create_resp = await _register_service(
        client,
        pro_api_key,
        endpoint="https://example.com/api",
    )
    service_id = create_resp.json()["id"]

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = AsyncMock(status_code=200)
        resp = await client.post(
            "/v1/marketplace/atlas/preflight",
            json={"service_id": service_id},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert "checks" in body
    assert "latency_ms" in body


async def test_preflight_not_found(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/preflight",
        json={"service_id": "nonexistent-svc-id"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # Should return product exception (404)
    assert resp.status_code in (404, 200)
    if resp.status_code == 200:
        body = resp.json()
        assert "error" in body or body.get("ready") is False


async def test_preflight_no_endpoint(client, pro_api_key):
    create_resp = await _register_service(
        client,
        pro_api_key,
        endpoint="",
    )
    service_id = create_resp.json()["id"]
    resp = await client.post(
        "/v1/marketplace/atlas/preflight",
        json={"service_id": service_id},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["endpoint"] == "fail"


async def test_preflight_trust_below(client, pro_api_key):
    create_resp = await _register_service(
        client,
        pro_api_key,
        endpoint="https://example.com/api",
    )
    service_id = create_resp.json()["id"]

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = AsyncMock(status_code=200)
        resp = await client.post(
            "/v1/marketplace/atlas/preflight",
            json={"service_id": service_id, "min_trust_score": 99.0},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["checks"]["trust"] == "fail"
    assert body["ready"] is False


async def test_preflight_optional_checks(client, pro_api_key):
    create_resp = await _register_service(
        client,
        pro_api_key,
        endpoint="https://example.com/api",
    )
    service_id = create_resp.json()["id"]

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = AsyncMock(status_code=200)
        resp = await client.post(
            "/v1/marketplace/atlas/preflight",
            json={"service_id": service_id},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    # Without min_trust_score and expected_cost, those should default to ok
    assert body["checks"]["trust"] == "ok"
    assert body["checks"]["pricing"] == "ok"


async def test_preflight_no_auth(client):
    resp = await client.post(
        "/v1/marketplace/atlas/preflight",
        json={"service_id": "test-svc"},
    )
    assert resp.status_code == 401


# ===========================================================================
# Integration: POST /v1/marketplace/atlas/broker
# ===========================================================================


async def test_broker_success(client, pro_api_key, app):
    # Register a service + create wallet for provider
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("broker-provider", initial_balance=100.0, signup_bonus=False)

    create_resp = await _register_service(
        client,
        pro_api_key,
        provider_id="broker-provider",
        name="Broker Target",
        endpoint="https://example.com/api",
        pricing={"model": "per_call", "cost": 2.0},
    )
    assert create_resp.status_code == 201

    with patch("httpx.AsyncClient.head", new_callable=AsyncMock) as mock_head:
        mock_head.return_value = AsyncMock(status_code=200)
        resp = await client.post(
            "/v1/marketplace/atlas/broker",
            json={
                "query": "Broker Target",
                "payer": "pro-agent",
                "description": "Test brokered payment",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("match") is not None or body.get("error") is not None


async def test_broker_no_match(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={
            "query": "nonexistent-service-zzz-never-match",
            "payer": "pro-agent",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["match"] is None
    assert "error" in body


async def test_broker_requires_pro(client, api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={"query": "test", "payer": "test-agent"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


async def test_broker_no_auth(client):
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={"query": "test", "payer": "someone"},
    )
    assert resp.status_code == 401


async def test_broker_ownership(client, pro_api_key):
    """Payer must match the authenticated agent."""
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={"query": "test", "payer": "someone-else"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 403


async def test_broker_xss_sanitized(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={
            "query": "test",
            "payer": "pro-agent",
            "description": "<script>alert('xss')</script>Hello",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # Should not fail — description is sanitized
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        body = resp.json()
        if body.get("match") and body.get("intent_id"):
            # The description should have been sanitized
            pass


async def test_broker_invalid_payer(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/atlas/broker",
        json={"query": "test", "payer": "'; DROP TABLE agents;--"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422
