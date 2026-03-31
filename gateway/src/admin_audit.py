"""Admin audit trail for admin-only tool operations.

Provides functions to log admin operations (both successful and denied)
to a dedicated admin_audit_log table in the billing database.

Params are sanitized before logging to strip secrets, tokens, and API keys.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiosqlite

logger = logging.getLogger("a2a.admin_audit")

# Field names whose values should be redacted in audit logs.
_SECRET_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "api_key",
        "token",
        "secret",
        "password",
        "authorization",
        "access_token",
        "refresh_token",
        "private_key",
        "secret_key",
        "credential",
        "credentials",
    }
)

# DDL for the admin_audit_log table.
ADMIN_AUDIT_LOG_DDL: str = """
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    agent_id        TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    params_json     TEXT NOT NULL,
    client_ip       TEXT,
    status          TEXT NOT NULL CHECK(status IN ('success', 'denied', 'error')),
    result_summary  TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_agent ON admin_audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_admin_audit_tool ON admin_audit_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_admin_audit_ts ON admin_audit_log(timestamp);
"""


def sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *params* with secret values redacted.

    - Fields whose key matches a known secret name are replaced with ``***REDACTED***``.
    - Internal ``_caller_*`` fields injected by the gateway are removed entirely.
    - Nested dicts are sanitized recursively.
    """
    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        # Strip internal caller-injected fields
        if key.startswith("_caller_"):
            continue
        if key.lower() in _SECRET_FIELD_NAMES:
            sanitized[key] = "***REDACTED***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_params(value)
        else:
            sanitized[key] = value
    return sanitized


async def ensure_admin_audit_table(db: aiosqlite.Connection) -> None:
    """Create the admin_audit_log table if it does not exist."""
    await db.executescript(ADMIN_AUDIT_LOG_DDL)
    await db.commit()


async def log_admin_operation(
    db: aiosqlite.Connection,
    *,
    agent_id: str,
    tool_name: str,
    params: dict[str, Any],
    client_ip: str | None,
    status: str,
    result_summary: str | None = None,
) -> int:
    """Write an admin audit record to the database.

    *params* are sanitized before storage to strip any secrets.
    Returns the row id of the inserted record.
    """
    now = time.time()
    sanitized = sanitize_params(params)
    params_json = json.dumps(sanitized, default=str)

    cursor = await db.execute(
        "INSERT INTO admin_audit_log "
        "(timestamp, agent_id, tool_name, params_json, client_ip, status, result_summary) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (now, agent_id, tool_name, params_json, client_ip, status, result_summary),
    )
    await db.commit()
    logger.info(
        "Admin audit: agent=%s tool=%s status=%s ip=%s",
        agent_id,
        tool_name,
        status,
        client_ip,
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def get_admin_audit_log(
    db: aiosqlite.Connection,
    *,
    agent_id: str | None = None,
    tool_name: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Retrieve admin audit log records.

    Optional filters: *agent_id* and *tool_name*.
    Returns records ordered by timestamp ascending.
    """
    query = "SELECT * FROM admin_audit_log WHERE 1=1"
    bind_params: list[Any] = []
    if agent_id is not None:
        query += " AND agent_id = ?"
        bind_params.append(agent_id)
    if tool_name is not None:
        query += " AND tool_name = ?"
        bind_params.append(tool_name)
    query += " ORDER BY timestamp ASC LIMIT ?"
    bind_params.append(limit)

    cursor = await db.execute(query, bind_params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]
