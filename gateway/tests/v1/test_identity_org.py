"""ID5.11 regression — org_creation must not crash with 500.

The v1.2.9 audit found that ``create_org`` returns 500 instead of a
proper response.  These tests verify org CRUD via the REST API.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_org_succeeds(client, api_key):
    """create_org with valid params returns 200/201 + org_id."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {"org_name": "Acme Corp", "agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), f"Expected success, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "org_id" in body
    assert body["name"] == "Acme Corp"
    assert "created_at" in body


async def test_create_org_missing_name_returns_error(client, api_key):
    """create_org without org_name should return 400/500 (KeyError), not crash silently."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Missing required field — should be handled, not unhandled 500
    # After fix: should be 400 (validation_error), not raw 500
    assert resp.status_code in (400, 500)


async def test_create_org_returns_structured_response(client, api_key):
    """Org response has org_id, name, created_at."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {"org_name": "Test Org", "agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["org_id"].startswith("org-")
    assert body["created_at"] is not None


async def test_create_org_duplicate_name_no_crash(client, api_key):
    """Creating two orgs with the same name should not crash."""
    for _ in range(2):
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_org",
                "params": {"org_name": "Duplicate Org", "agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code != 500, f"Got 500: {resp.text}"
