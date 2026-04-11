"""T-3 sandbox parity: multi-tenant isolation against live sandbox.

Runs the same class of probe the audit personas used. Uses three
real API keys on ``sandbox.greenhelix.net`` so the test path is
Cloudflare → nginx → gunicorn → gateway, not an in-process
TestClient. Catches the class of bug where an in-process test
passes but the real stack leaks.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestSandboxMultiTenantIsolation:
    async def test_health_reachable(self, sandbox_client):
        """Sanity: sandbox is alive and returns the expected shape."""
        resp = await sandbox_client.get("/v1/health")
        assert resp.status_code == 200, f"sandbox /v1/health: {resp.status_code} {resp.text[:200]}"
        body = resp.json()
        assert body.get("status") == "ok"
        assert "version" in body

    async def test_free_tier_cannot_list_infra_keys(self, sandbox_client, free_key):
        """FREE-tier must get 403 on the admin-only infra surface."""
        resp = await sandbox_client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {free_key}"},
        )
        assert resp.status_code == 403, f"FREE should be denied /v1/infra/keys, got {resp.status_code}"

    async def test_pro_tier_cannot_list_infra_keys(self, sandbox_client, pro_key):
        """PRO-tier must also get 403 — only admin sees /v1/infra/*."""
        resp = await sandbox_client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {pro_key}"},
        )
        assert resp.status_code == 403, f"PRO should be denied /v1/infra/keys, got {resp.status_code}"

    async def test_admin_tier_can_list_infra_keys(self, sandbox_client, admin_key):
        """Admin succeeds — proves the gate isn't broken for everyone."""
        resp = await sandbox_client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 200, f"admin should see /v1/infra/keys, got {resp.status_code} {resp.text[:200]}"
