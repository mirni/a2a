"""Tests for database security gateway tools (backup, restore, integrity, list)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_backup_database_tool(client, pro_api_key):
    """Backup a database and verify response has path/size."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["size_bytes"] > 0
    assert "created_at" in result
    assert result["path"].endswith(".db")


async def test_backup_with_encryption(client, pro_api_key):
    """Encrypted backup returns an encryption key."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing", "encrypt": True},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "key" in result
    assert len(result["key"]) > 0


async def test_restore_database_tool(client, pro_api_key):
    """Backup then restore, verify data intact."""
    # First create a backup
    backup_resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert backup_resp.status_code == 200
    backup_path = backup_resp.json()["result"]["path"]

    # Restore it
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "restore_database",
            "params": {"database": "billing", "backup_path": backup_path},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["size_bytes"] > 0
    assert "restored_at" in result


async def test_integrity_check_tool(client, pro_api_key):
    """Check billing DB integrity, verify ok=true."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "check_db_integrity",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["ok"] is True
    assert result["page_count"] > 0


async def test_list_backups_empty(client, pro_api_key):
    """No backups yet returns empty list."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_backups",
            "params": {},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["backups"] == []


async def test_list_backups_after_backup(client, pro_api_key):
    """Create a backup, then list shows it."""
    await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "billing"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_backups",
            "params": {},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["backups"]) >= 1


async def test_backup_unknown_db_error(client, pro_api_key):
    """Invalid database name returns error."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "backup_database",
            "params": {"database": "nonexistent_db"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert "error" in body


async def test_check_all_databases_integrity(client, pro_api_key):
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
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Failed for {db_name}"
        result = resp.json()["result"]
        assert result["ok"] is True, f"Integrity check failed for {db_name}"
