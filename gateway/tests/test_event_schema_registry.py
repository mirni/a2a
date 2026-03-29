"""Tests for P2-14: Event Schema Registry tools."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestRegisterEventSchema:
    """Tests for the register_event_schema tool."""

    async def test_tool_exists_in_catalog(self, client, api_key):
        """register_event_schema should be in the catalog."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_event_schema",
                "params": {
                    "event_type": "test.event",
                    "schema": {"type": "object", "properties": {"foo": {"type": "string"}}},
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_register_and_retrieve_schema(self, client, api_key):
        """Should register a schema and retrieve it."""
        schema = {"type": "object", "properties": {"amount": {"type": "number"}}}

        # Register
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "register_event_schema",
                "params": {"event_type": "payment.completed", "schema": schema},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        # Retrieve
        resp2 = await client.post(
            "/v1/execute",
            json={
                "tool": "get_event_schema",
                "params": {"event_type": "payment.completed"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["success"] is True
        assert data2["result"]["schema"] == schema
        assert data2["result"]["event_type"] == "payment.completed"

    async def test_overwrite_existing_schema(self, client, api_key):
        """Registering a schema for an existing event type should overwrite."""
        schema_v1 = {"type": "object", "properties": {"v": {"type": "integer"}}}
        schema_v2 = {"type": "object", "properties": {"v": {"type": "string"}}}

        await client.post(
            "/v1/execute",
            json={
                "tool": "register_event_schema",
                "params": {"event_type": "order.created", "schema": schema_v1},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        await client.post(
            "/v1/execute",
            json={
                "tool": "register_event_schema",
                "params": {"event_type": "order.created", "schema": schema_v2},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_event_schema",
                "params": {"event_type": "order.created"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["schema"] == schema_v2

    async def test_get_nonexistent_schema(self, client, api_key):
        """Retrieving a schema that doesn't exist should return not found."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_event_schema",
                "params": {"event_type": "nonexistent.event"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"].get("found") is False

    async def test_register_missing_params(self, client, api_key):
        """Should fail when required params are missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "register_event_schema", "params": {"event_type": "only.type"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400

    async def test_get_event_schema_exists_in_catalog(self, client, api_key):
        """get_event_schema should be in the catalog."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_event_schema",
                "params": {"event_type": "anything"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_get_missing_event_type_param(self, client, api_key):
        """Should fail when event_type param is missing for get_event_schema."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_event_schema", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
