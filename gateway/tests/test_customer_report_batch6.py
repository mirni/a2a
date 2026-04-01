"""Batch 6 — P2 API Improvements tests (Items 19-21).

Item 19: remove_agent_from_org — Expose as tool + last-owner guard
Item 20: OpenAPI — Add per-tool output schemas for key tools
Item 21: Webhook — Require HMAC secret
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _exec(client, tool, params, key):
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {key}"},
    )


# ============================================================================
# Item 19: remove_agent_from_org — Expose as tool + last-owner guard
# ============================================================================


class TestRemoveAgentFromOrg:
    """remove_agent_from_org tool should be exposed and guard last owner."""

    async def test_remove_agent_from_org_tool_exists(self, client, app):
        """remove_agent_from_org should be callable as a tool."""
        key = await _create_agent(app, "org-owner-19", tier="free", balance=1000.0)

        # Register the agent in identity first
        await _exec(client, "register_agent", {"agent_id": "org-owner-19"}, key)

        # Create org
        resp = await _exec(
            client,
            "create_org",
            {"org_name": "Test Org 19", "agent_id": "org-owner-19"},
            key,
        )
        assert resp.status_code in (200, 201)
        org_id = resp.json()["org_id"]

        # Add a second member
        key2 = await _create_agent(app, "org-member-19", tier="free", balance=1000.0)
        await _exec(client, "register_agent", {"agent_id": "org-member-19"}, key2)
        resp = await _exec(
            client,
            "add_agent_to_org",
            {"org_id": org_id, "agent_id": "org-member-19"},
            key,
        )
        assert resp.status_code == 200

        # Remove second member — should succeed
        resp = await _exec(
            client,
            "remove_agent_from_org",
            {"org_id": org_id, "agent_id": "org-member-19"},
            key,
        )
        assert resp.status_code == 200

    async def test_remove_last_owner_rejected(self, client, app):
        """Removing the sole owner from an org should fail."""
        key = await _create_agent(app, "sole-owner-19", tier="free", balance=1000.0)
        await _exec(client, "register_agent", {"agent_id": "sole-owner-19"}, key)

        resp = await _exec(
            client,
            "create_org",
            {"org_name": "Solo Org 19", "agent_id": "sole-owner-19"},
            key,
        )
        assert resp.status_code in (200, 201)
        org_id = resp.json()["org_id"]

        # Attempt to remove the sole owner — should be rejected
        resp = await _exec(
            client,
            "remove_agent_from_org",
            {"org_id": org_id, "agent_id": "sole-owner-19"},
            key,
        )
        assert resp.status_code != 200  # Should be 400 or 409


# ============================================================================
# Item 20: OpenAPI — Per-tool output schemas for key tools
# ============================================================================


class TestOpenAPIOutputSchemas:
    """Key tools should have typed output_schema in the OpenAPI spec."""

    async def test_key_tools_have_output_schema(self, client):
        """High-traffic tools should have output schemas with typed properties."""
        resp = await client.get("/v1/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()

        # Check that the spec itself contains per-tool response schemas
        # referenced from the execute endpoint or components
        schemas = spec["components"]["schemas"]

        # We expect output schemas for key tools to be present as components
        expected_output_schemas = [
            "GetBalanceOutput",
            "CreateIntentOutput",
            "GetPaymentHistoryOutput",
        ]
        for schema_name in expected_output_schemas:
            assert schema_name in schemas, f"Missing output schema: {schema_name}"
            props = schemas[schema_name].get("properties", {})
            assert len(props) > 0, f"{schema_name} should have typed properties"


# ============================================================================
# Item 21: Webhook — Require HMAC secret
# ============================================================================


class TestWebhookRequireSecret:
    """register_webhook should require a non-empty secret."""

    async def test_register_webhook_without_secret_fails(self, client, app):
        """Register webhook without secret should return 400."""
        key = await _create_agent(app, "hook-agent-21", tier="pro", balance=1000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "hook-agent-21",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
            },
            key,
        )
        assert resp.status_code == 400

    async def test_register_webhook_with_empty_secret_fails(self, client, app):
        """Register webhook with empty string secret should return 400."""
        key = await _create_agent(app, "hook-agent-21b", tier="pro", balance=1000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "hook-agent-21b",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "",
            },
            key,
        )
        assert resp.status_code == 400

    async def test_register_webhook_with_secret_succeeds(self, client, app):
        """Register webhook with valid secret should succeed."""
        key = await _create_agent(app, "hook-agent-21c", tier="pro", balance=1000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "hook-agent-21c",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "my-webhook-secret",
            },
            key,
        )
        assert resp.status_code in (200, 201)
