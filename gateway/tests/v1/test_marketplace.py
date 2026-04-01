"""Tests for marketplace REST endpoints — /v1/marketplace/."""

from __future__ import annotations

import pytest

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
    }
    payload.update({k: v for k, v in overrides.items() if k not in payload})
    return await client.post(
        "/v1/marketplace/services",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# POST /v1/marketplace/services  (register_service)
# ---------------------------------------------------------------------------


async def test_register_service_via_rest(client, pro_api_key):
    resp = await _register_service(client, pro_api_key)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "Location" in resp.headers


async def test_register_service_no_auth(client):
    resp = await client.post(
        "/v1/marketplace/services",
        json={"provider_id": "a", "name": "s", "description": "d", "category": "c"},
    )
    assert resp.status_code == 401


async def test_register_service_extra_fields(client, pro_api_key):
    resp = await client.post(
        "/v1/marketplace/services",
        json={"provider_id": "a", "name": "s", "description": "d", "category": "c", "extra": 1},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/marketplace/services  (search_services)
# ---------------------------------------------------------------------------


async def test_search_services_via_rest(client, api_key):
    resp = await client.get(
        "/v1/marketplace/services",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "services" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/marketplace/services/{service_id}
# ---------------------------------------------------------------------------


async def test_get_service_via_rest(client, pro_api_key):
    create_resp = await _register_service(client, pro_api_key)
    service_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/marketplace/services/{service_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == service_id


# ---------------------------------------------------------------------------
# PUT /v1/marketplace/services/{service_id}
# ---------------------------------------------------------------------------


async def test_update_service_via_rest(client, pro_api_key):
    create_resp = await _register_service(client, pro_api_key)
    service_id = create_resp.json()["id"]
    resp = await client.put(
        f"/v1/marketplace/services/{service_id}",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


# ---------------------------------------------------------------------------
# POST /v1/marketplace/services/{service_id}/deactivate
# ---------------------------------------------------------------------------


async def test_deactivate_service_via_rest(client, pro_api_key):
    create_resp = await _register_service(client, pro_api_key)
    service_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/marketplace/services/{service_id}/deactivate",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"


# ---------------------------------------------------------------------------
# POST /v1/marketplace/services/{service_id}/ratings  (rate_service)
# ---------------------------------------------------------------------------


async def test_rate_service_via_rest(client, pro_api_key):
    create_resp = await _register_service(client, pro_api_key)
    service_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/marketplace/services/{service_id}/ratings",
        json={"rating": 5, "review": "Great!"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["rating"] == 5


# ---------------------------------------------------------------------------
# GET /v1/marketplace/services/{service_id}/ratings
# ---------------------------------------------------------------------------


async def test_get_service_ratings_via_rest(client, pro_api_key):
    create_resp = await _register_service(client, pro_api_key)
    service_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/marketplace/services/{service_id}/ratings",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "average_rating" in body
    assert "ratings" in body


# ---------------------------------------------------------------------------
# GET /v1/marketplace/match
# ---------------------------------------------------------------------------


async def test_best_match_via_rest(client, api_key):
    resp = await client.get(
        "/v1/marketplace/match?query=analytics",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "matches" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/marketplace/agents
# ---------------------------------------------------------------------------


async def test_search_agents_via_rest(client, api_key):
    resp = await client.get(
        "/v1/marketplace/agents?query=test",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "agents" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/marketplace/strategies
# ---------------------------------------------------------------------------


async def test_list_strategies_via_rest(client, api_key):
    resp = await client.get(
        "/v1/marketplace/strategies",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "strategies" in resp.json()


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


async def test_marketplace_response_headers(client, api_key):
    resp = await client.get(
        "/v1/marketplace/services",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
