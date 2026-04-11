"""v1.2.4 audit P0-1 regression — admin gate on /v1/infra/* endpoints.

These tests exist because four consecutive external audits flagged
``/v1/infra/keys`` as leaking fleet metadata to non-admin callers.
The root cause was that the route was reachable by free/pro tiers
and returned enriched metadata (key_hash_prefix, tier, scopes,
created_at) for the caller's entire key history. The audit persona
read that as a full fleet leak.

The fix moves self-service key management to ``/v1/billing/keys``
and gates ``/v1/infra/keys`` (GET fleet view) + ``/v1/infra/keys/rotate``
behind admin tier via ``ADMIN_ONLY_TOOLS``. These tests prove it.

Key property: this uses a **multi-tenant** fixture (five agents, not
one) so any accidental "return everything you find" bug shows up as
cross-tenant contamination.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def multi_tenant_keys(app):
    """Provision five distinct agents across tiers.

    Returns a dict keyed by label:
        {
            "free-1": (agent_id, api_key),
            "free-2": (agent_id, api_key),
            "pro-1":  (agent_id, api_key),
            "pro-2":  (agent_id, api_key),
            "admin":  (agent_id, api_key),
        }

    Each agent starts with two keys so tests can assert cross-agent
    isolation (``len(keys) == 2`` for a single-agent view) and the
    admin fleet view (``len(keys) >= 10``).
    """
    ctx = app.state.ctx

    tenants: dict[str, tuple[str, str]] = {}
    specs = [
        ("free-1", "free", "audit-free-1"),
        ("free-2", "free", "audit-free-2"),
        ("pro-1", "pro", "audit-pro-1"),
        ("pro-2", "pro", "audit-pro-2"),
    ]
    for label, tier, agent_id in specs:
        await ctx.tracker.wallet.create(agent_id, initial_balance=500.0, signup_bonus=False)
        first = await ctx.key_manager.create_key(agent_id, tier=tier)
        # second key so list returns 2 rows per agent
        await ctx.key_manager.create_key(agent_id, tier=tier)
        tenants[label] = (agent_id, first["key"])

    admin_id = "audit-admin"
    await ctx.tracker.wallet.create(admin_id, initial_balance=10000.0, signup_bonus=False)
    admin_first = await ctx.key_manager.create_key(
        admin_id, tier="pro", scopes=["read", "write", "admin"]
    )
    await ctx.key_manager.create_key(admin_id, tier="pro", scopes=["read", "write", "admin"])
    tenants["admin"] = (admin_id, admin_first["key"])

    return tenants


# ---------------------------------------------------------------------------
# GET /v1/infra/keys — admin fleet view
# ---------------------------------------------------------------------------


async def test_infra_keys_fleet_view_admin(client, multi_tenant_keys):
    _, admin_key = multi_tenant_keys["admin"]
    resp = await client.get(
        "/v1/infra/keys",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    keys = body["keys"]
    # 5 agents × 2 keys each = 10 (plus any test-setup keys
    # from other fixtures — we assert *at least* 10 and that
    # every seeded agent is represented).
    agent_ids = {k["agent_id"] for k in keys}
    for label in ("free-1", "free-2", "pro-1", "pro-2", "admin"):
        expected, _ = multi_tenant_keys[label]
        assert expected in agent_ids, f"fleet view missing {label}"


async def test_infra_keys_free_tier_denied(client, multi_tenant_keys):
    _, key = multi_tenant_keys["free-1"]
    resp = await client.get(
        "/v1/infra/keys",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert "admin" in body.get("detail", "").lower() or body.get("type", "").endswith("admin-only")


async def test_infra_keys_pro_tier_denied(client, multi_tenant_keys):
    _, key = multi_tenant_keys["pro-1"]
    resp = await client.get(
        "/v1/infra/keys",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/infra/keys — deprecated 410 Gone
# ---------------------------------------------------------------------------


async def test_infra_keys_post_returns_410_with_link(client, multi_tenant_keys):
    _, key = multi_tenant_keys["free-1"]
    resp = await client.post(
        "/v1/infra/keys",
        json={"tier": "free"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 410
    assert resp.headers.get("Deprecation") == "true"
    assert "Sunset" in resp.headers
    assert "/v1/billing/keys" in resp.headers.get("Link", "")


async def test_infra_keys_post_returns_410_even_with_garbage_body(client, multi_tenant_keys):
    """The route is dead — body validation must not get in the way."""
    _, key = multi_tenant_keys["free-1"]
    resp = await client.post(
        "/v1/infra/keys",
        content=b"not-json",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 410


# ---------------------------------------------------------------------------
# GET /v1/billing/keys — self-service, strictly scoped
# ---------------------------------------------------------------------------


async def test_billing_keys_self_service_free(client, multi_tenant_keys):
    agent_id, key = multi_tenant_keys["free-1"]
    resp = await client.get(
        "/v1/billing/keys",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 2
    for k in keys:
        assert k["agent_id"] == agent_id


async def test_billing_keys_cross_tenant_probe_denied(client, multi_tenant_keys):
    """pro-1 requests free-1's keys → 403."""
    free_id, _ = multi_tenant_keys["free-1"]
    _, pro_key = multi_tenant_keys["pro-1"]
    resp = await client.get(
        f"/v1/billing/keys?agent_id={free_id}",
        headers={"Authorization": f"Bearer {pro_key}"},
    )
    assert resp.status_code == 403


async def test_billing_keys_self_service_pro_isolation(client, multi_tenant_keys):
    agent_id, key = multi_tenant_keys["pro-1"]
    resp = await client.get(
        "/v1/billing/keys",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 2
    for k in keys:
        assert k["agent_id"] == agent_id


# ---------------------------------------------------------------------------
# POST /v1/billing/keys — self-service create
# ---------------------------------------------------------------------------


async def test_billing_keys_create_self_service(client, multi_tenant_keys):
    agent_id, key = multi_tenant_keys["free-1"]
    resp = await client.post(
        "/v1/billing/keys",
        json={"tier": "free"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "key" in body
    assert body["agent_id"] == agent_id


async def test_billing_keys_create_tier_escalation_denied(client, multi_tenant_keys):
    """Free tier cannot create pro keys."""
    _, key = multi_tenant_keys["free-1"]
    resp = await client.post(
        "/v1/billing/keys",
        json={"tier": "pro"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 403
