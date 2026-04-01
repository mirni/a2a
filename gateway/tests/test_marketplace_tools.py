"""Tests for marketplace tools: get_service, update_service, deactivate_service (P0-2/3/4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _register_service(client, api_key):
    """Helper: register a service and return its ID."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_service",
            "params": {
                "provider_id": "pro-agent",
                "name": "Test Service",
                "description": "A test service",
                "category": "analytics",
                "tags": ["test"],
                "endpoint": "https://example.com/api",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_get_service(client, pro_api_key):
    """get_service should return a service by ID."""
    service_id = await _register_service(client, pro_api_key)

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_service", "params": {"service_id": service_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["id"] == service_id
    assert result["name"] == "Test Service"
    assert result["description"] == "A test service"
    assert result["category"] == "analytics"


async def test_get_service_not_found(client, api_key):
    """get_service with an unknown ID should return 404."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_service", "params": {"service_id": "nonexistent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_update_service(client, pro_api_key):
    """update_service should update fields on an existing service."""
    service_id = await _register_service(client, pro_api_key)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "update_service",
            "params": {
                "service_id": service_id,
                "name": "Updated Service",
                "description": "Updated description",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["id"] == service_id
    assert result["name"] == "Updated Service"
    assert result["description"] == "Updated description"


async def test_update_service_not_found(client, api_key):
    """update_service with unknown ID should return 404."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "update_service",
            "params": {"service_id": "nonexistent", "name": "X"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404


async def test_deactivate_service(client, pro_api_key):
    """deactivate_service should set the service status to inactive."""
    service_id = await _register_service(client, pro_api_key)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "deactivate_service",
            "params": {"service_id": service_id},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["id"] == service_id
    assert result["status"] == "inactive"


async def test_deactivate_service_not_found(client, api_key):
    """deactivate_service with unknown ID should return 404."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "deactivate_service",
            "params": {"service_id": "nonexistent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 404
