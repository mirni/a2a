"""Security hardening tests for P0 items from v2 customer report.

P0-3: freeze_wallet/unfreeze_wallet tier escalation
P0-5: backup_database key leak in response
P0-6: create_api_key tier escalation (free user creating pro keys)
P0-7: resolve_dispute resolved_by impersonation
P0-8: restore_database path traversal
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# P0-5: backup_database should NOT return encryption key in response
# ---------------------------------------------------------------------------


class TestBackupKeyLeak:
    """backup_database must not expose the Fernet encryption key."""

    async def test_encrypted_backup_does_not_leak_key(self, client, admin_api_key):
        """When encrypt=true, the response must NOT include the key field."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "backup_database",
                "params": {"database": "billing", "encrypt": True},
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        # The key must NOT be in the API response — it should be stored server-side
        assert "key" not in result, (
            f"SECURITY: encryption key leaked in API response: {result.get('key', '')[:10]}..."
        )
        # But should have a key_id for later retrieval
        assert "key_id" in result


# ---------------------------------------------------------------------------
# P0-6: create_api_key tier escalation prevention
# ---------------------------------------------------------------------------


class TestKeyTierEscalation:
    """create_api_key must not allow tier escalation."""

    async def test_free_user_cannot_create_pro_key(self, client, api_key):
        """A free-tier agent should not be able to create a pro-tier key."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent", "tier": "pro"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should be rejected — either 403 or 200 with error
        if resp.status_code == 200:
            data = resp.json()
            # If it returns 200, the tier should NOT be "pro"
            assert not data.get("success") or data["result"]["tier"] != "pro", (
                "SECURITY: free-tier user escalated to pro tier"
            )
        else:
            assert resp.status_code == 403

    async def test_free_user_cannot_create_admin_key(self, client, api_key):
        """A free-tier agent should not be able to create an admin-tier key."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent", "tier": "admin"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert not data.get("success") or data["result"]["tier"] != "admin", (
                "SECURITY: free-tier user escalated to admin tier"
            )
        else:
            assert resp.status_code == 403

    async def test_pro_user_cannot_create_admin_key(self, client, pro_api_key):
        """A pro-tier agent should not be able to create an admin-tier key."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "pro-agent", "tier": "admin"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert not data.get("success") or data["result"]["tier"] != "admin", (
                "SECURITY: pro-tier user escalated to admin tier"
            )
        else:
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# P0-7: resolve_dispute resolved_by must use authenticated caller
# ---------------------------------------------------------------------------


class TestDisputeImpersonation:
    """resolve_dispute must override resolved_by with the authenticated caller."""

    async def test_resolved_by_cannot_be_spoofed(self, client, app, admin_api_key):
        """resolved_by should be set to the authenticated agent, not the caller-supplied value."""
        ctx = app.state.ctx

        # Create wallet for dispute payee (admin-agent wallet already exists from fixture)
        await ctx.tracker.wallet.create("dispute-payee", initial_balance=1000.0, signup_bonus=False)

        # Create escrow via API (admin key has agent_id=admin-agent)
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_escrow",
                "params": {
                    "payer": "admin-agent",
                    "payee": "dispute-payee",
                    "amount": 100,
                },
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200, f"create_escrow failed: {resp.json()}"
        escrow_id = resp.json()["result"]["id"]

        # Open a dispute via API
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "open_dispute",
                "params": {
                    "escrow_id": escrow_id,
                    "opener": "admin-agent",
                    "reason": "test dispute",
                },
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200, f"open_dispute failed: {resp.json()}"
        dispute_id = resp.json()["result"]["id"]

        # Try to resolve with a spoofed resolved_by
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "resolve_dispute",
                "params": {
                    "dispute_id": dispute_id,
                    "resolution": "refund",
                    "resolved_by": "malicious-agent",
                },
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # resolved_by must be the authenticated agent, NOT the spoofed value
        assert data["result"]["resolved_by"] != "malicious-agent", (
            "SECURITY: resolved_by was spoofed — should use authenticated caller"
        )
        assert data["result"]["resolved_by"] == "admin-agent"


# ---------------------------------------------------------------------------
# P0-8: restore_database path traversal prevention
# ---------------------------------------------------------------------------


class TestRestorePathTraversal:
    """restore_database must validate backup_path to prevent path traversal."""

    async def test_path_traversal_rejected(self, client, admin_api_key):
        """backup_path containing '..' should be rejected."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "restore_database",
                "params": {
                    "database": "billing",
                    "backup_path": "/tmp/../etc/passwd",
                },
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        # Should be rejected, not just file-not-found
        data = resp.json()
        # Either 400 (validation error) or 500 with path traversal rejection
        assert resp.status_code in (400, 500)
        if resp.status_code == 500:
            error_msg = str(data.get("error", {}).get("message", ""))
            # Should not say "file not found" for a path traversal attempt
            assert "path traversal" in error_msg.lower() or "invalid" in error_msg.lower()

    async def test_absolute_path_outside_data_dir_rejected(self, client, admin_api_key):
        """backup_path outside the backup directory should be rejected."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "restore_database",
                "params": {
                    "database": "billing",
                    "backup_path": "/etc/shadow",
                },
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        # Should be a security rejection, not just file-not-found
        assert resp.status_code in (400, 500)


# ---------------------------------------------------------------------------
# P0-3: freeze_wallet tier_required catalog fix
# ---------------------------------------------------------------------------


class TestFreezeWalletTier:
    """freeze_wallet and unfreeze_wallet must be admin-only."""

    async def test_free_user_cannot_freeze_wallet(self, client, api_key):
        """A free-tier user must not be able to freeze any wallet."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "freeze_wallet",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403

    async def test_pro_user_cannot_freeze_wallet(self, client, pro_api_key):
        """A pro-tier user must not be able to freeze any wallet."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "freeze_wallet",
                "params": {"agent_id": "pro-agent"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_freeze_wallet(self, client, admin_api_key, app):
        """An admin should be able to freeze wallets."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("freeze-target", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "freeze_wallet",
                "params": {"agent_id": "freeze-target"},
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"]["frozen"] is True
