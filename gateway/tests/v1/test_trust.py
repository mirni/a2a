"""Tests for trust REST endpoints — /v1/trust/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_server(client, key, **overrides):
    payload = {
        "name": overrides.get("name", "test-server"),
        "url": overrides.get("url", "https://example.com/api"),
    }
    payload.update({k: v for k, v in overrides.items() if k not in payload})
    return await client.post(
        "/v1/trust/servers",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# POST /v1/trust/servers  (register_server)
# ---------------------------------------------------------------------------


async def test_register_server_via_rest(client, api_key):
    resp = await _register_server(client, api_key)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "Location" in resp.headers


async def test_register_server_no_auth(client):
    resp = await client.post(
        "/v1/trust/servers",
        json={"name": "s", "url": "https://example.com"},
    )
    assert resp.status_code == 401


async def test_register_server_extra_fields(client, api_key):
    resp = await client.post(
        "/v1/trust/servers",
        json={"name": "s", "url": "https://example.com", "extra": 1},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/trust/servers  (search_servers)
# ---------------------------------------------------------------------------


async def test_search_servers_via_rest(client, api_key):
    resp = await client.get(
        "/v1/trust/servers",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "servers" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/trust/servers/{server_id}/score
# ---------------------------------------------------------------------------


async def test_get_trust_score_via_rest(client, api_key):
    create_resp = await _register_server(client, api_key)
    server_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/trust/servers/{server_id}/score",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "composite_score" in body


async def test_get_trust_score_with_window(client, api_key):
    create_resp = await _register_server(client, api_key, name="ts-window")
    server_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/trust/servers/{server_id}/score?window=7d",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PUT /v1/trust/servers/{server_id}  (update_server)
# ---------------------------------------------------------------------------


async def test_update_server_via_rest(client, pro_api_key):
    create_resp = await _register_server(client, pro_api_key, name="upd-server")
    server_id = create_resp.json()["id"]
    resp = await client.put(
        f"/v1/trust/servers/{server_id}",
        json={"name": "updated-server"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated-server"


# ---------------------------------------------------------------------------
# DELETE /v1/trust/servers/{server_id}
# ---------------------------------------------------------------------------


async def test_delete_server_via_rest(client, pro_api_key):
    create_resp = await _register_server(client, pro_api_key, name="del-server")
    server_id = create_resp.json()["id"]
    resp = await client.delete(
        f"/v1/trust/servers/{server_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# GET /v1/trust/servers/{server_id}/sla
# ---------------------------------------------------------------------------


async def test_check_sla_compliance_via_rest(client, pro_api_key):
    create_resp = await _register_server(client, pro_api_key, name="sla-server")
    server_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/trust/servers/{server_id}/sla",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


async def test_trust_response_headers(client, api_key):
    resp = await client.get(
        "/v1/trust/servers",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers


# ---------------------------------------------------------------------------
# Negative / edge-case tests
# ---------------------------------------------------------------------------


async def test_delete_nonexistent_server(client, pro_api_key):
    """DELETE a non-existent server -> 404."""
    resp = await client.delete(
        "/v1/trust/servers/nonexistent-server-id",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 404


async def test_get_score_nonexistent_server(client, api_key):
    """GET score for non-existent server -> 404."""
    resp = await client.get(
        "/v1/trust/servers/nonexistent-server-id/score",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_search_servers_with_name_filter(client, api_key):
    """Search with name filter."""
    await _register_server(client, api_key, name="findme-server")
    resp = await client.get(
        "/v1/trust/servers?name=findme",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
