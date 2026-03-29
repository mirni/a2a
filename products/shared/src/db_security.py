"""SQLite database security utilities: hardening, backup, restore, integrity, encryption."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timezone

import aiosqlite


async def harden_connection(db: aiosqlite.Connection) -> None:
    """Apply security-hardening PRAGMAs to an open aiosqlite connection.

    Sets WAL journal mode, enables foreign keys, secure delete, and
    incremental auto-vacuum.  Safe to call multiple times (idempotent).
    """
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA secure_delete=ON")
    # auto_vacuum can only change before tables exist; apply + VACUUM on empty DBs
    cur = await db.execute("PRAGMA page_count")
    page_count = (await cur.fetchone())[0]
    if page_count <= 1:
        await db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        await db.execute("VACUUM")


async def backup_database(source_path: str, dest_path: str) -> dict:
    """Create a hot backup of a SQLite database using the built-in backup API.

    Returns metadata dict with path, size_bytes, created_at, source.
    """
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source database not found: {source_path}")

    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    def _do_backup() -> None:
        src_conn = sqlite3.connect(source_path)
        dst_conn = sqlite3.connect(dest_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

    await asyncio.to_thread(_do_backup)

    return {
        "path": dest_path,
        "size_bytes": os.path.getsize(dest_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source_path,
    }


async def restore_database(backup_path: str, target_path: str) -> dict:
    """Restore a SQLite database from a backup file.

    Creates target directory if needed and applies harden_connection after restore.
    Returns metadata dict with path, size_bytes, restored_at, source_backup.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    def _do_restore() -> None:
        src_conn = sqlite3.connect(backup_path)
        dst_conn = sqlite3.connect(target_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

    await asyncio.to_thread(_do_restore)

    return {
        "path": target_path,
        "size_bytes": os.path.getsize(target_path),
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "source_backup": backup_path,
    }


async def integrity_check(db_path: str) -> dict:
    """Run integrity and page diagnostics on a SQLite database.

    Returns dict with ok, details, page_count, freelist_count, path, checked_at.
    """

    def _do_check() -> dict:
        conn = sqlite3.connect(db_path)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]
            return {
                "ok": result == "ok",
                "details": result,
                "page_count": page_count,
                "freelist_count": freelist_count,
            }
        except sqlite3.DatabaseError as exc:
            return {
                "ok": False,
                "details": str(exc),
                "page_count": 0,
                "freelist_count": 0,
            }
        finally:
            conn.close()

    info = await asyncio.to_thread(_do_check)
    info["path"] = db_path
    info["checked_at"] = datetime.now(timezone.utc).isoformat()
    return info


async def encrypt_backup(
    source_path: str, dest_path: str, key: str | None = None
) -> dict:
    """Encrypt a file using Fernet symmetric encryption.

    Auto-generates a key if none provided.
    Returns dict with path, size_bytes, key, created_at.
    """
    from cryptography.fernet import Fernet

    if key is None:
        key = Fernet.generate_key().decode()

    fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def _do_encrypt() -> None:
        with open(source_path, "rb") as f:
            data = f.read()
        encrypted = fernet.encrypt(data)
        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(encrypted)

    await asyncio.to_thread(_do_encrypt)

    return {
        "path": dest_path,
        "size_bytes": os.path.getsize(dest_path),
        "key": key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def decrypt_backup(source_path: str, dest_path: str, key: str) -> dict:
    """Decrypt a Fernet-encrypted file.

    Returns dict with path, size_bytes, decrypted_at.
    """
    from cryptography.fernet import Fernet

    fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def _do_decrypt() -> None:
        with open(source_path, "rb") as f:
            data = f.read()
        decrypted = fernet.decrypt(data)
        dest_dir = os.path.dirname(dest_path)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(decrypted)

    await asyncio.to_thread(_do_decrypt)

    return {
        "path": dest_path,
        "size_bytes": os.path.getsize(dest_path),
        "decrypted_at": datetime.now(timezone.utc).isoformat(),
    }
