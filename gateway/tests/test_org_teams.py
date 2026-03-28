"""Tests for P3-23: Org/Team Concept (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_org(client, api_key):
    """Create an org and get back its details."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {"org_name": "Acme Corp"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["name"] == "Acme Corp"
    assert "org_id" in result
    assert "created_at" in result


async def test_get_org(client, api_key):
    """Get an org by its ID."""
    # Create org first
    resp1 = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {"org_name": "Beta Inc"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    org_id = resp1.json()["result"]["org_id"]

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_org",
            "params": {"org_id": org_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["org_id"] == org_id
    assert result["name"] == "Beta Inc"
    assert result["members"] == []


async def test_add_agent_to_org(client, api_key, app):
    """Add an agent to an org and verify membership."""
    ctx = app.state.ctx

    # Register an agent identity
    await ctx.identity_api.register_agent("org-agent-1")

    # Create org
    resp1 = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {"org_name": "Gamma LLC"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    org_id = resp1.json()["result"]["org_id"]

    # Add agent to org
    resp2 = await client.post(
        "/v1/execute",
        json={
            "tool": "add_agent_to_org",
            "params": {"org_id": org_id, "agent_id": "org-agent-1"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 200
    result = resp2.json()["result"]
    assert result["agent_id"] == "org-agent-1"
    assert result["org_id"] == org_id

    # Verify agent is listed as member
    resp3 = await client.post(
        "/v1/execute",
        json={
            "tool": "get_org",
            "params": {"org_id": org_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    result3 = resp3.json()["result"]
    assert any(m["agent_id"] == "org-agent-1" for m in result3["members"])


async def test_get_org_not_found(client, api_key):
    """Get a non-existent org."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_org",
            "params": {"org_id": "nonexistent-org-id"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Should return error or empty result
    body = resp.json()
    if resp.status_code == 200:
        result = body["result"]
        assert result.get("error") or result.get("org_id") is None
    else:
        assert resp.status_code in (404, 400, 500)


async def test_add_agent_to_nonexistent_org(client, api_key, app):
    """Adding agent to non-existent org should fail."""
    ctx = app.state.ctx
    await ctx.identity_api.register_agent("orphan-agent")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "add_agent_to_org",
            "params": {"org_id": "fake-org", "agent_id": "orphan-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    body = resp.json()
    if resp.status_code == 200:
        assert "error" in body.get("result", {})
    else:
        assert resp.status_code in (404, 400, 500)


async def test_create_org_missing_name(client, api_key):
    """Missing org_name should return 400."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_org",
            "params": {},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
