"""Tests for the webhook delivery system."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_webhook(client, pro_api_key, app):
    """Pro tier should be able to register a webhook."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/webhook",
                "event_types": ["billing.deposit", "billing.usage_recorded"],
                "secret": "my-secret-key",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["id"].startswith("whk-")
    assert data["agent_id"] == "pro-agent"
    assert data["url"] == "https://example.com/webhook"
    assert data["active"] == 1


@pytest.mark.asyncio
async def test_list_webhooks(client, pro_api_key, app):
    """Should list registered webhooks for an agent."""
    # Register a webhook first
    await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/hook1",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_webhooks",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["webhooks"]) >= 1


@pytest.mark.asyncio
async def test_delete_webhook(client, pro_api_key, app):
    """Should deactivate a webhook."""
    # Register
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/to-delete",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    webhook_id = resp.json()["id"]

    # Delete
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "delete_webhook",
            "params": {"webhook_id": webhook_id},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Verify it's gone from list
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_webhooks",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    webhooks = resp.json()["webhooks"]
    ids = [w["id"] for w in webhooks]
    assert webhook_id not in ids


@pytest.mark.asyncio
async def test_webhook_requires_pro(client, api_key):
    """Free tier should not access webhook tools."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "test-agent",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403
