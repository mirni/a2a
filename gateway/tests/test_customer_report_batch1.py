"""Batch 1 — P0 Security Critical tests (Items 1-5).

TDD Red Phase: These tests MUST fail before implementation.

Item 1: resolve_dispute admin-only gate
Item 2: Webhook ownership checks
Item 3: Webhook URL SSRF protection
Item 4: revoke_api_key tier fix (free tier)
Item 5: ToolPricing.tier_required enum fix
"""

from __future__ import annotations

import hashlib
import secrets

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _create_admin_agent(app, agent_id: str = "admin-agent") -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=10000.0, signup_bonus=False)
    raw_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(key_hash=key_hash, agent_id=agent_id, tier="admin")
    return raw_key


async def _exec(client, tool: str, params: dict, key: str):
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {key}"},
    )


# ============================================================================
# Item 1: resolve_dispute — admin-only gate
# ============================================================================


class TestResolveDisputeAdminOnly:
    """resolve_dispute must only be callable by admin-tier agents."""

    async def test_free_tier_cannot_resolve_dispute(self, client, app):
        """Free-tier agent calling resolve_dispute gets 403."""
        ctx = app.state.ctx
        free_key = await _create_agent(app, "free-disputer-1", tier="free", balance=5000.0)
        await _create_agent(app, "payee-d1", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="free-disputer-1", payee="payee-d1", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="free-disputer-1", reason="test")

        resp = await _exec(
            client,
            "resolve_dispute",
            {
                "dispute_id": dispute["id"],
                "resolution": "refund",
                "resolved_by": "free-disputer-1",
            },
            free_key,
        )
        assert resp.status_code == 403

    async def test_pro_tier_cannot_resolve_dispute(self, client, app):
        """Pro-tier agent calling resolve_dispute gets 403."""
        ctx = app.state.ctx
        pro_key = await _create_agent(app, "pro-disputer-1", tier="pro", balance=5000.0)
        await _create_agent(app, "payee-d2", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="pro-disputer-1", payee="payee-d2", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="pro-disputer-1", reason="test")

        resp = await _exec(
            client,
            "resolve_dispute",
            {
                "dispute_id": dispute["id"],
                "resolution": "refund",
                "resolved_by": "pro-disputer-1",
            },
            pro_key,
        )
        assert resp.status_code == 403

    async def test_admin_can_resolve_dispute(self, client, app):
        """Admin-tier agent can resolve a dispute."""
        ctx = app.state.ctx
        admin_key = await _create_admin_agent(app, "admin-resolver-1")
        await _create_agent(app, "buyer-adm1", tier="free", balance=5000.0)
        await _create_agent(app, "seller-adm1", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-adm1", payee="seller-adm1", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-adm1", reason="test")

        resp = await _exec(
            client,
            "resolve_dispute",
            {
                "dispute_id": dispute["id"],
                "resolution": "refund",
                "resolved_by": "admin-resolver-1",
            },
            admin_key,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"


# ============================================================================
# Item 2: Webhook tools — ownership checks
# ============================================================================


class TestWebhookOwnership:
    """delete_webhook, get_webhook_deliveries, test_webhook must
    verify that the webhook belongs to the caller."""

    async def test_delete_webhook_by_other_agent_is_forbidden(self, client, app):
        """Agent B cannot delete Agent A's webhook."""
        key_a = await _create_agent(app, "wh-owner-a", tier="pro", balance=5000.0)
        key_b = await _create_agent(app, "wh-intruder-b", tier="pro", balance=5000.0)

        # Agent A registers webhook
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "wh-owner-a",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key_a,
        )
        webhook_id = resp.json()["id"]

        # Agent B tries to delete it
        resp = await _exec(client, "delete_webhook", {"webhook_id": webhook_id}, key_b)
        assert resp.status_code == 403

    async def test_get_webhook_deliveries_by_other_agent_is_forbidden(self, client, app):
        """Agent B cannot read Agent A's webhook deliveries."""
        key_a = await _create_agent(app, "wh-owner-c", tier="pro", balance=5000.0)
        key_b = await _create_agent(app, "wh-intruder-d", tier="pro", balance=5000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "wh-owner-c",
                "url": "https://example.com/hook2",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key_a,
        )
        webhook_id = resp.json()["id"]

        resp = await _exec(client, "get_webhook_deliveries", {"webhook_id": webhook_id}, key_b)
        assert resp.status_code == 403

    async def test_test_webhook_by_other_agent_is_forbidden(self, client, app):
        """Agent B cannot test Agent A's webhook."""
        key_a = await _create_agent(app, "wh-owner-e", tier="pro", balance=5000.0)
        key_b = await _create_agent(app, "wh-intruder-f", tier="pro", balance=5000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "wh-owner-e",
                "url": "https://example.com/hook3",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key_a,
        )
        webhook_id = resp.json()["id"]

        resp = await _exec(client, "test_webhook", {"webhook_id": webhook_id}, key_b)
        assert resp.status_code == 403

    async def test_owner_can_delete_own_webhook(self, client, app):
        """Owner can delete their own webhook."""
        key_a = await _create_agent(app, "wh-owner-g", tier="pro", balance=5000.0)

        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "wh-owner-g",
                "url": "https://example.com/hook4",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key_a,
        )
        webhook_id = resp.json()["id"]

        resp = await _exec(client, "delete_webhook", {"webhook_id": webhook_id}, key_a)
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# ============================================================================
# Item 3: Webhook URL — SSRF protection
# ============================================================================


class TestWebhookSSRF:
    """Webhook registration must reject non-HTTPS and private IP URLs."""

    async def test_http_url_rejected(self, client, app):
        """http:// URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-1", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-1",
                "url": "http://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_localhost_rejected(self, client, app):
        """127.0.0.1 URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-2", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-2",
                "url": "https://127.0.0.1/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_private_ip_192_168_rejected(self, client, app):
        """192.168.x.x URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-3", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-3",
                "url": "https://192.168.1.1/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_private_ip_10_rejected(self, client, app):
        """10.x.x.x URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-4", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-4",
                "url": "https://10.0.0.1/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_metadata_ip_rejected(self, client, app):
        """169.254.169.254 (cloud metadata) URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-5", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-5",
                "url": "https://169.254.169.254/latest/meta-data",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_ipv6_loopback_rejected(self, client, app):
        """::1 (IPv6 loopback) URLs should be rejected."""
        key = await _create_agent(app, "ssrf-agent-6", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-6",
                "url": "https://[::1]/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code != 200

    async def test_valid_https_url_accepted(self, client, app):
        """Valid https://example.com/hook should be accepted."""
        key = await _create_agent(app, "ssrf-agent-7", tier="pro", balance=5000.0)
        resp = await _exec(
            client,
            "register_webhook",
            {
                "agent_id": "ssrf-agent-7",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
            key,
        )
        assert resp.status_code in (200, 201)


# ============================================================================
# Item 4: revoke_api_key — move to free tier
# ============================================================================


class TestRevokeApiKeyFreeTier:
    """revoke_api_key is admin-only (BFLA audit fix). Non-admin must get 403."""

    async def test_free_tier_cannot_revoke_key(self, client, app):
        """Free-tier agent trying to revoke a key must get 403 (admin-only)."""
        key = await _create_agent(app, "revoke-free-agent", tier="free", balance=1000.0)

        resp = await _exec(
            client,
            "revoke_api_key",
            {"agent_id": "revoke-free-agent", "key_hash_prefix": "abcd1234"},
            key,
        )
        assert resp.status_code == 403


# ============================================================================
# Item 5: ToolPricing.tier_required — fix enum
# ============================================================================


class TestToolPricingEnum:
    """OpenAPI spec tier_required enum must include all 4 tiers."""

    async def test_tier_enum_includes_all_tiers(self, client):
        """ToolPricing.tier_required.enum includes free, starter, pro, enterprise."""
        resp = await client.get("/v1/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        tier_enum = data["components"]["schemas"]["ToolPricing"]["properties"]["tier_required"]["enum"]
        assert "free" in tier_enum
        assert "starter" in tier_enum
        assert "pro" in tier_enum
        assert "enterprise" in tier_enum
