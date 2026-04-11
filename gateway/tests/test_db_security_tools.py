"""Tests for database security gateway tools (backup, restore, integrity, list)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_backup_database_tool(client, admin_api_key):
    """Backup a database and verify response has filename/size.

    v1.2.4 (audit v1.2.3 MED-7): responses expose ``filename`` (basename)
    and ``database`` instead of absolute ``path`` to avoid leaking the
    server filesystem layout.
    """
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["size_bytes"] > 0
    assert "created_at" in result
    assert "path" not in result
    assert result["filename"].endswith(".db")
    assert result["database"] == "billing"


async def test_backup_with_encryption(client, admin_api_key):
    """Encrypted backup returns a key_id (key stored server-side, never in response)."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing", "encrypt": True},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    # Security: key must NOT be in the response — only key_id for retrieval
    assert "key" not in result, "Encryption key should not be in API response"
    assert "key_id" in result
    assert len(result["key_id"]) > 0


async def test_restore_database_tool(client, admin_api_key):
    """Backup then restore, verify data intact.

    v1.2.4 (audit v1.2.3 MED-7): restore accepts a ``filename`` (basename)
    that is resolved server-side against the managed backup dir.
    """
    # First create a backup
    backup_resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert backup_resp.status_code == 200
    filename = backup_resp.json()["filename"]

    # Restore it
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "restore_database",
            "params": {"database": "billing", "filename": filename},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["size_bytes"] > 0
    assert "restored_at" in result
    # Response must not leak absolute paths
    assert "path" not in result


async def test_integrity_check_tool(client, admin_api_key):
    """Check billing DB integrity, verify ok=true."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "check_db_integrity",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["ok"] is True
    assert result["page_count"] > 0


async def test_list_backups_empty(client, admin_api_key):
    """No backups yet returns empty list."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_backups",
            "params": {},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["backups"] == []


async def test_list_backups_after_backup(client, admin_api_key):
    """Create a backup, then list shows it."""
    await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_backups",
            "params": {},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert len(result["backups"]) >= 1


async def test_backup_unknown_db_error(client, admin_api_key):
    """Invalid database name returns error."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "nonexistent_db"},
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "type" in body
    assert body["status"] == 400


async def test_check_all_databases_integrity(client, admin_api_key):
    """Loop all known databases and check integrity."""
    databases = [
        "billing",
        "paywall",
        "payments",
        "marketplace",
        "trust",
        "identity",
        "event_bus",
        "webhooks",
        "disputes",
        "messaging",
    ]
    for db_name in databases:
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "check_db_integrity",
                "params": {"database": db_name},
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200, f"Failed for {db_name}"
        result = resp.json()
        assert result["ok"] is True, f"Integrity check failed for {db_name}"
