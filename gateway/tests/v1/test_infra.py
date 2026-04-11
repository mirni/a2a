"""Tests for infrastructure REST endpoints — /v1/infra/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_webhook(client, key, agent_id="pro-agent"):
    return await client.post(
        "/v1/infra/webhooks",
        json={
            "url": "https://example.com/hook",
            "event_types": ["payment.completed"],
            "secret": "test-secret-123",
        },
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# POST /v1/infra/keys  (create_api_key)
# ---------------------------------------------------------------------------


async def test_create_api_key_via_rest(client, api_key):
    resp = await client.post(
        "/v1/infra/keys",
        json={"tier": "free"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "key" in body


async def test_create_api_key_no_auth(client):
    resp = await client.post("/v1/infra/keys", json={"tier": "free"})
    assert resp.status_code == 401


async def test_create_api_key_extra_fields(client, api_key):
    resp = await client.post(
        "/v1/infra/keys",
        json={"tier": "free", "extra": 1},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/infra/keys  (list_api_keys)
# ---------------------------------------------------------------------------


async def test_list_api_keys_via_rest(client, api_key):
    resp = await client.get(
        "/v1/infra/keys",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "keys" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/infra/keys/revoke  (revoke_api_key)
# ---------------------------------------------------------------------------


async def test_revoke_api_key_via_rest(client, app):
    """revoke_api_key is admin-only; use admin-tier key."""
    import hashlib
    import secrets

    ctx = app.state.ctx
    admin_id = "admin-revoke-infra"
    try:
        await ctx.tracker.wallet.create(admin_id, initial_balance=10000.0, signup_bonus=False)
    except Exception:
        pass
    raw_admin_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_admin_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(key_hash=key_hash, agent_id=admin_id, tier="admin")

    # Create a key to revoke
    new_key_info = await ctx.key_manager.create_key(admin_id, tier="free")
    revoke_prefix = new_key_info["key_hash"][:8]

    resp = await client.post(
        "/v1/infra/keys/revoke",
        json={"key_hash_prefix": revoke_prefix},
        headers={"Authorization": f"Bearer {raw_admin_key}"},
    )
    assert resp.status_code == 200
    assert "revoked" in resp.json()


async def test_revoke_api_key_non_admin_denied(client, api_key):
    """Non-admin calling revoke_api_key via REST must get 403."""
    resp = await client.post(
        "/v1/infra/keys/revoke",
        json={"key_hash_prefix": "abcd1234"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/infra/keys/rotate  (rotate_key)
# ---------------------------------------------------------------------------


async def test_rotate_key_via_rest(client, api_key):
    resp = await client.post(
        "/v1/infra/keys/rotate",
        json={"current_key": api_key},
        headers={
            "Authorization": f"Bearer {api_key}",
            # v1.2.2 audit HIGH-7: rotation now requires an explicit
            # confirmation header so it cannot happen by accident.
            "X-Rotate-Confirmation": "confirm",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "new_key" in body
    assert body["new_key"] != api_key


async def test_rotate_key_requires_confirmation_header(client, api_key):
    """v1.2.2 audit HIGH-7 regression — missing header returns 428."""
    resp = await client.post(
        "/v1/infra/keys/rotate",
        json={"current_key": api_key},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 428
    body = resp.json()
    assert "confirmation" in body.get("detail", "").lower()


# ---------------------------------------------------------------------------
# POST /v1/infra/webhooks  (register_webhook)
# ---------------------------------------------------------------------------


async def test_register_webhook_via_rest(client, pro_api_key):
    resp = await _register_webhook(client, pro_api_key)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "Location" in resp.headers


async def test_register_webhook_extra_fields(client, pro_api_key):
    resp = await client.post(
        "/v1/infra/webhooks",
        json={
            "url": "https://example.com/hook",
            "event_types": ["x"],
            "secret": "s",
            "extra": 1,
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/infra/webhooks  (list_webhooks)
# ---------------------------------------------------------------------------


async def test_list_webhooks_via_rest(client, pro_api_key):
    resp = await client.get(
        "/v1/infra/webhooks",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "webhooks" in resp.json()


# ---------------------------------------------------------------------------
# DELETE /v1/infra/webhooks/{webhook_id}
# ---------------------------------------------------------------------------


async def test_delete_webhook_via_rest(client, pro_api_key):
    create_resp = await _register_webhook(client, pro_api_key)
    webhook_id = create_resp.json()["id"]
    resp = await client.delete(
        f"/v1/infra/webhooks/{webhook_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# GET /v1/infra/webhooks/{webhook_id}/deliveries
# ---------------------------------------------------------------------------


async def test_get_webhook_deliveries_via_rest(client, pro_api_key):
    create_resp = await _register_webhook(client, pro_api_key)
    webhook_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/infra/webhooks/{webhook_id}/deliveries",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "deliveries" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/infra/webhooks/{webhook_id}/test
# ---------------------------------------------------------------------------


async def test_test_webhook_via_rest(client, pro_api_key):
    create_resp = await _register_webhook(client, pro_api_key)
    webhook_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/infra/webhooks/{webhook_id}/test",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # test_webhook may fail to deliver (no real endpoint), but the route should work
    assert resp.status_code in (200, 502)


# ---------------------------------------------------------------------------
# POST /v1/infra/events  (publish_event)
# ---------------------------------------------------------------------------


async def test_publish_event_via_rest(client, api_key):
    resp = await client.post(
        "/v1/infra/events",
        json={
            "event_type": "test.event",
            "source": "test-agent",
            "payload": {"key": "value"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "event_id" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/infra/events  (get_events)
# ---------------------------------------------------------------------------


async def test_get_events_via_rest(client, api_key):
    resp = await client.get(
        "/v1/infra/events",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "events" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/infra/events/schemas  (register_event_schema)
# ---------------------------------------------------------------------------


async def test_register_event_schema_via_rest(client, api_key):
    resp = await client.post(
        "/v1/infra/events/schemas",
        json={
            "event_type": "test.event",
            "schema": {"type": "object", "properties": {"key": {"type": "string"}}},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["registered"] is True


# ---------------------------------------------------------------------------
# GET /v1/infra/events/schemas/{event_type}
# ---------------------------------------------------------------------------


async def test_get_event_schema_via_rest(client, api_key):
    # First register a schema
    await client.post(
        "/v1/infra/events/schemas",
        json={
            "event_type": "test.schema",
            "schema": {"type": "object"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp = await client.get(
        "/v1/infra/events/schemas/test.schema",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["found"] is True


# ---------------------------------------------------------------------------
# GET /v1/infra/audit-log  (get_global_audit_log — admin only)
# ---------------------------------------------------------------------------


async def test_get_global_audit_log_via_rest(client, admin_api_key):
    resp = await client.get(
        "/v1/infra/audit-log",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    assert "entries" in resp.json()


async def test_get_global_audit_log_forbidden_for_non_admin(client, api_key):
    resp = await client.get(
        "/v1/infra/audit-log",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/infra/databases/{database}/backup
# ---------------------------------------------------------------------------


async def test_backup_database_via_rest(client, admin_api_key):
    resp = await client.post(
        "/v1/infra/databases/billing/backup",
        json={},
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # v1.2.4 audit MED-7: responses expose ``filename`` (basename) and
    # ``database`` instead of the absolute ``path``.
    assert "filename" in body
    assert "database" in body
    assert "path" not in body


# ---------------------------------------------------------------------------
# GET /v1/infra/databases/{database}/integrity
# ---------------------------------------------------------------------------


async def test_check_db_integrity_via_rest(client, admin_api_key):
    resp = await client.get(
        "/v1/infra/databases/billing/integrity",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    assert "ok" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/infra/databases/backups  (list_backups)
# ---------------------------------------------------------------------------


async def test_list_backups_via_rest(client, admin_api_key):
    resp = await client.get(
        "/v1/infra/databases/backups",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    assert "backups" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/infra/databases/{database}/restore
# ---------------------------------------------------------------------------


async def test_restore_database_via_rest(client, admin_api_key):
    # First create a backup
    backup_resp = await client.post(
        "/v1/infra/databases/billing/backup",
        json={},
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    # v1.2.4 audit MED-7: restore now accepts a ``filename`` (basename)
    # that is resolved server-side against the managed backup dir.
    filename = backup_resp.json()["filename"]

    resp = await client.post(
        "/v1/infra/databases/billing/restore",
        json={"filename": filename},
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


async def test_infra_response_headers(client, api_key):
    resp = await client.get(
        "/v1/infra/keys",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
