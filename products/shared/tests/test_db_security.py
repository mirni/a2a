"""Tests for SQLite database security utilities (TDD — written before implementation)."""

from __future__ import annotations

import asyncio
import os
import sqlite3

import aiosqlite
import pytest

from src.db_security import (
    backup_database,
    decrypt_backup,
    encrypt_backup,
    harden_connection,
    integrity_check,
    restore_database,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_test_db(path: str) -> None:
    """Create a small test database with sample data."""
    db = await aiosqlite.connect(path)
    await db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    await db.execute("INSERT INTO items (name) VALUES ('alpha')")
    await db.execute("INSERT INTO items (name) VALUES ('beta')")
    await db.commit()
    await db.close()


# ---------------------------------------------------------------------------
# TestHardenConnection
# ---------------------------------------------------------------------------


class TestHardenConnection:
    @pytest.mark.asyncio
    async def test_enables_wal_mode(self, tmp_path):
        db = await aiosqlite.connect(str(tmp_path / "test.db"))
        await harden_connection(db)
        row = await db.execute_fetchall("PRAGMA journal_mode")
        assert row[0][0] == "wal"
        await db.close()

    @pytest.mark.asyncio
    async def test_enables_foreign_keys(self, tmp_path):
        db = await aiosqlite.connect(str(tmp_path / "test.db"))
        await harden_connection(db)
        row = await db.execute_fetchall("PRAGMA foreign_keys")
        assert row[0][0] == 1
        await db.close()

    @pytest.mark.asyncio
    async def test_enables_secure_delete(self, tmp_path):
        db = await aiosqlite.connect(str(tmp_path / "test.db"))
        await harden_connection(db)
        row = await db.execute_fetchall("PRAGMA secure_delete")
        assert row[0][0] == 1
        await db.close()

    @pytest.mark.asyncio
    async def test_enables_auto_vacuum(self, tmp_path):
        db = await aiosqlite.connect(str(tmp_path / "test.db"))
        await harden_connection(db)
        row = await db.execute_fetchall("PRAGMA auto_vacuum")
        # 2 = incremental
        assert row[0][0] == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_path):
        db = await aiosqlite.connect(str(tmp_path / "test.db"))
        await harden_connection(db)
        await harden_connection(db)
        row = await db.execute_fetchall("PRAGMA journal_mode")
        assert row[0][0] == "wal"
        await db.close()


# ---------------------------------------------------------------------------
# TestBackupDatabase
# ---------------------------------------------------------------------------


class TestBackupDatabase:
    @pytest.mark.asyncio
    async def test_creates_backup_file(self, tmp_path):
        src = str(tmp_path / "source.db")
        dest = str(tmp_path / "backup.db")
        await _create_test_db(src)
        await backup_database(src, dest)
        assert os.path.exists(dest)

    @pytest.mark.asyncio
    async def test_backup_contains_data(self, tmp_path):
        src = str(tmp_path / "source.db")
        dest = str(tmp_path / "backup.db")
        await _create_test_db(src)
        await backup_database(src, dest)
        conn = sqlite3.connect(dest)
        rows = conn.execute("SELECT name FROM items").fetchall()
        conn.close()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_nonexistent_source_raises(self, tmp_path):
        src = str(tmp_path / "missing.db")
        dest = str(tmp_path / "backup.db")
        with pytest.raises(FileNotFoundError):
            await backup_database(src, dest)

    @pytest.mark.asyncio
    async def test_returns_metadata(self, tmp_path):
        src = str(tmp_path / "source.db")
        dest = str(tmp_path / "backup.db")
        await _create_test_db(src)
        meta = await backup_database(src, dest)
        assert meta["path"] == dest
        assert meta["size_bytes"] > 0
        assert "created_at" in meta
        assert meta["source"] == src

    @pytest.mark.asyncio
    async def test_works_with_wal_db(self, tmp_path):
        src = str(tmp_path / "wal_source.db")
        dest = str(tmp_path / "backup.db")
        db = await aiosqlite.connect(src)
        await harden_connection(db)
        await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        await db.execute("INSERT INTO t (id) VALUES (1)")
        await db.commit()
        await db.close()

        await backup_database(src, dest)
        conn = sqlite3.connect(dest)
        rows = conn.execute("SELECT id FROM t").fetchall()
        conn.close()
        assert rows == [(1,)]


# ---------------------------------------------------------------------------
# TestRestoreDatabase
# ---------------------------------------------------------------------------


class TestRestoreDatabase:
    @pytest.mark.asyncio
    async def test_restores_data(self, tmp_path):
        src = str(tmp_path / "source.db")
        backup = str(tmp_path / "backup.db")
        target = str(tmp_path / "restored.db")
        await _create_test_db(src)
        await backup_database(src, backup)
        await restore_database(backup, target)

        conn = sqlite3.connect(target)
        rows = conn.execute("SELECT name FROM items ORDER BY name").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_missing_backup_raises(self, tmp_path):
        backup = str(tmp_path / "missing.db")
        target = str(tmp_path / "restored.db")
        with pytest.raises(FileNotFoundError):
            await restore_database(backup, target)

    @pytest.mark.asyncio
    async def test_creates_target_directory(self, tmp_path):
        src = str(tmp_path / "source.db")
        backup = str(tmp_path / "backup.db")
        target = str(tmp_path / "subdir" / "restored.db")
        await _create_test_db(src)
        await backup_database(src, backup)
        await restore_database(backup, target)
        assert os.path.exists(target)

    @pytest.mark.asyncio
    async def test_returns_metadata(self, tmp_path):
        src = str(tmp_path / "source.db")
        backup = str(tmp_path / "backup.db")
        target = str(tmp_path / "restored.db")
        await _create_test_db(src)
        await backup_database(src, backup)
        meta = await restore_database(backup, target)
        assert meta["path"] == target
        assert meta["size_bytes"] > 0
        assert "restored_at" in meta
        assert meta["source_backup"] == backup


# ---------------------------------------------------------------------------
# TestIntegrityCheck
# ---------------------------------------------------------------------------


class TestIntegrityCheck:
    @pytest.mark.asyncio
    async def test_valid_db_passes(self, tmp_path):
        db_path = str(tmp_path / "good.db")
        await _create_test_db(db_path)
        result = await integrity_check(db_path)
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_page_count_present(self, tmp_path):
        db_path = str(tmp_path / "good.db")
        await _create_test_db(db_path)
        result = await integrity_check(db_path)
        assert isinstance(result["page_count"], int)
        assert result["page_count"] > 0

    @pytest.mark.asyncio
    async def test_freelist_count_present(self, tmp_path):
        db_path = str(tmp_path / "good.db")
        await _create_test_db(db_path)
        result = await integrity_check(db_path)
        assert isinstance(result["freelist_count"], int)

    @pytest.mark.asyncio
    async def test_reports_corruption(self, tmp_path):
        db_path = str(tmp_path / "corrupt.db")
        await _create_test_db(db_path)
        # Corrupt heavily: overwrite data pages (skip the 100-byte header)
        size = os.path.getsize(db_path)
        with open(db_path, "r+b") as f:
            f.seek(100)
            f.write(b"\xff" * min(size - 100, 4096))
        result = await integrity_check(db_path)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# TestEncryptDecrypt
# ---------------------------------------------------------------------------


class TestEncryptDecrypt:
    @pytest.mark.asyncio
    async def test_encrypt_produces_different_content(self, tmp_path):
        db_path = str(tmp_path / "source.db")
        enc_path = str(tmp_path / "encrypted.bin")
        await _create_test_db(db_path)
        result = await encrypt_backup(db_path, enc_path)

        original = open(db_path, "rb").read()
        encrypted = open(enc_path, "rb").read()
        assert original != encrypted
        assert "key" in result

    @pytest.mark.asyncio
    async def test_round_trip(self, tmp_path):
        db_path = str(tmp_path / "source.db")
        enc_path = str(tmp_path / "encrypted.bin")
        dec_path = str(tmp_path / "decrypted.db")
        await _create_test_db(db_path)

        enc_result = await encrypt_backup(db_path, enc_path)
        await decrypt_backup(enc_path, dec_path, enc_result["key"])

        conn = sqlite3.connect(dec_path)
        rows = conn.execute("SELECT name FROM items ORDER BY name").fetchall()
        conn.close()
        assert [r[0] for r in rows] == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_wrong_key_raises(self, tmp_path):
        db_path = str(tmp_path / "source.db")
        enc_path = str(tmp_path / "encrypted.bin")
        dec_path = str(tmp_path / "decrypted.db")
        await _create_test_db(db_path)

        await encrypt_backup(db_path, enc_path)
        # Use a different key
        from cryptography.fernet import Fernet

        wrong_key = Fernet.generate_key().decode()
        with pytest.raises(Exception):
            await decrypt_backup(enc_path, dec_path, wrong_key)

    @pytest.mark.asyncio
    async def test_auto_generates_key(self, tmp_path):
        db_path = str(tmp_path / "source.db")
        enc_path = str(tmp_path / "encrypted.bin")
        await _create_test_db(db_path)
        result = await encrypt_backup(db_path, enc_path)
        assert "key" in result
        assert len(result["key"]) > 0

    @pytest.mark.asyncio
    async def test_uses_provided_key(self, tmp_path):
        from cryptography.fernet import Fernet

        db_path = str(tmp_path / "source.db")
        enc_path = str(tmp_path / "encrypted.bin")
        dec_path = str(tmp_path / "decrypted.db")
        my_key = Fernet.generate_key().decode()
        await _create_test_db(db_path)

        result = await encrypt_backup(db_path, enc_path, key=my_key)
        assert result["key"] == my_key

        await decrypt_backup(enc_path, dec_path, my_key)
        conn = sqlite3.connect(dec_path)
        rows = conn.execute("SELECT count(*) FROM items").fetchone()
        conn.close()
        assert rows[0] == 2
