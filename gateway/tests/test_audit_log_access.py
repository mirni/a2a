"""Tests for cross-tenant audit log exposure fix (P2-5).

Verifies that get_global_audit_log requires admin scope:
- Free-tier users get 403 (insufficient_tier)
- Pro-tier users without admin scope get 403 (admin_only)
- Admin-scoped users can access it successfully
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestGlobalAuditLogAccess:
    """get_global_audit_log must be restricted to admin-scoped keys only."""

    async def test_free_tier_gets_403(self, client, api_key):
        """Free-tier user should be denied access (insufficient tier or admin_only)."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_global_audit_log", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["type"].endswith("/insufficient-tier") or body["type"].endswith("/admin-only")

    async def test_pro_tier_without_admin_scope_gets_403(self, client, pro_api_key):
        """Pro-tier user without admin scope should be denied (admin_only)."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_global_audit_log", "params": {}},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["type"].endswith("/admin-only")
        assert "admin" in body["detail"].lower()

    async def test_admin_scoped_user_can_access(self, client, admin_api_key):
        """Admin-scoped user should be able to access the global audit log."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_global_audit_log", "params": {}},
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "entries" in body["result"]
