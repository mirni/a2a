"""Smoke test for the v1.2.4 P1 multi-tenant test fixture.

The fixture itself is the payload — if this test passes, any
downstream security test using ``multi_tenant_keys`` has five
isolated tenants, correct tier assignment, and two keys per
agent so that key-fleet probes have something to enumerate.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_multi_tenant]


class TestMultiTenantFixture:
    async def test_all_five_tenants_present(self, multi_tenant_keys):
        assert set(multi_tenant_keys.keys()) == {
            "free_a",
            "free_b",
            "pro_a",
            "pro_b",
            "admin",
        }

    async def test_each_tenant_has_two_distinct_keys(self, multi_tenant_keys):
        for label, (_agent, k1, k2) in multi_tenant_keys.items():
            assert k1 != k2, f"{label} has duplicate keys"

    async def test_wallets_funded(self, client, multi_tenant_keys):
        for label, (agent_id, key, _k2) in multi_tenant_keys.items():
            resp = await client.get(
                f"/v1/billing/wallets/{agent_id}/balance",
                headers={"Authorization": f"Bearer {key}"},
            )
            assert resp.status_code == 200, f"{label} balance read failed"

    async def test_free_tier_cannot_reach_admin_only(self, client, multi_tenant_keys):
        """Cross-tier admin gate: free tenants must not see /v1/infra/keys."""
        _agent, key, _k2 = multi_tenant_keys["free_a"]
        resp = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_pro_tier_cannot_reach_admin_only(self, client, multi_tenant_keys):
        """Pro tenants must not see /v1/infra/keys either."""
        _agent, key, _k2 = multi_tenant_keys["pro_a"]
        resp = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_admin_tenant_reaches_admin_only(self, client, multi_tenant_keys):
        _agent, key, _k2 = multi_tenant_keys["admin"]
        resp = await client.get(
            "/v1/infra/keys",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_cross_tenant_isolation(self, client, multi_tenant_keys):
        """free_a must not see free_b's keys on /v1/billing/keys."""
        agent_a, key_a, _ = multi_tenant_keys["free_a"]
        agent_b, _, _ = multi_tenant_keys["free_b"]
        resp = await client.get(
            f"/v1/billing/keys?agent_id={agent_b}",
            headers={"Authorization": f"Bearer {key_a}"},
        )
        # Either 403 (blocked) or 200 with only own data is acceptable.
        # A leak would be 200 with agent_b's keys listed.
        assert resp.status_code in (200, 403), resp.text
        if resp.status_code == 200:
            body = resp.json()
            # Whatever shape the route returns, it must not contain
            # agent_b in any key record.
            assert agent_b not in str(body), f"tenant {agent_a} saw {agent_b}'s data in /v1/billing/keys"
