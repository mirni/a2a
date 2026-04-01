"""Tests for P2-8: register_server tool."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_register_server_tool_exists(client, api_key):
    """register_server should be recognized as a valid tool."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_server",
            "params": {
                "name": "test-server",
                "url": "https://example.com/api",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    data = resp.json()
    assert data.get("error", {}).get("code") != "unknown_tool"


async def test_register_server_creates_server(client, api_key):
    """register_server should create a server and return its details."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_server",
            "params": {
                "name": "my-server",
                "url": "https://my-server.example.com",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["name"] == "my-server"
    assert result["url"] == "https://my-server.example.com"
    assert "id" in result
    assert "transport_type" in result
