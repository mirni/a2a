"""Infrastructure tool functions: events, webhooks, keys, DB ops."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from gateway.src.lifespan import AppContext

# ---------------------------------------------------------------------------
# Paywall / Audit
# ---------------------------------------------------------------------------


async def _get_global_audit_log(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    entries = await ctx.paywall_storage.get_global_audit_log(
        since=params.get("since"),
        limit=params.get("limit", 100),
    )
    return {"entries": entries}


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------


async def _publish_event(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    event_id = await ctx.event_bus.publish(
        event_type=params["event_type"],
        source=params["source"],
        payload=params.get("payload", {}),
    )
    return {"event_id": event_id}


async def _get_events(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    events = await ctx.event_bus.get_events(
        event_type=params.get("event_type"),
        since_id=params.get("since_id", 0),
        limit=params.get("limit", 100),
    )
    return {"events": events}


# ---------------------------------------------------------------------------
# Event Schema Registry (P2-14)
# ---------------------------------------------------------------------------


async def _register_event_schema(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Register a JSON schema for an event type."""
    import json as _json

    event_type = params["event_type"]
    schema = params["schema"]
    schema_json = _json.dumps(schema, sort_keys=True)

    db = ctx.event_bus.db

    import time as _time

    now = _time.time()
    await db.execute(
        """
        INSERT INTO event_schemas (event_type, schema, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(event_type) DO UPDATE SET schema = excluded.schema, updated_at = excluded.updated_at
        """,
        (event_type, schema_json, now, now),
    )
    await db.commit()
    return {"event_type": event_type, "registered": True}


async def _get_event_schema(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Retrieve the registered JSON schema for an event type."""
    import json as _json

    event_type = params["event_type"]
    db = ctx.event_bus.db

    cursor = await db.execute(
        "SELECT event_type, schema FROM event_schemas WHERE event_type = ?",
        (event_type,),
    )
    row = await cursor.fetchone()
    if row is None:
        return {"event_type": event_type, "found": False}

    return {
        "event_type": row[0],
        "schema": _json.loads(row[1]),
        "found": True,
    }


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


async def _register_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    result = await ctx.webhook_manager.register(
        agent_id=params["agent_id"],
        url=params["url"],
        event_types=params["event_types"],
        secret=params.get("secret", ""),
        filter_agent_ids=params.get("filter_agent_ids"),
    )
    return result


async def _list_webhooks(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    webhooks = await ctx.webhook_manager.list_webhooks(params["agent_id"])
    return {"webhooks": webhooks}


async def _delete_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    deleted = await ctx.webhook_manager.delete_webhook(params["webhook_id"])
    return {"deleted": deleted}


async def _get_webhook_deliveries(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    deliveries = await ctx.webhook_manager.get_delivery_history(
        webhook_id=params["webhook_id"],
        limit=params.get("limit", 50),
    )
    return {"deliveries": deliveries}


# ---------------------------------------------------------------------------
# Webhook Test/Ping (P2-15)
# ---------------------------------------------------------------------------


async def _test_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Send a test.ping event to a registered webhook and return the delivery result."""
    from gateway.src.tool_errors import ToolNotFoundError

    webhook_id = params["webhook_id"]
    wm = ctx.webhook_manager

    try:
        return await wm.send_test_ping(webhook_id)
    except LookupError:
        raise ToolNotFoundError(f"Webhook not found: {webhook_id}") from None


# ---------------------------------------------------------------------------
# Key Rotation
# ---------------------------------------------------------------------------


async def _rotate_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Revoke current key and create a new one with the same tier."""
    current_key = params["current_key"]
    key_info = await ctx.key_manager.validate_key(current_key)
    agent_id = key_info["agent_id"]
    tier = key_info["tier"]

    revoked = await ctx.key_manager.revoke_key(current_key)
    new_key_info = await ctx.key_manager.create_key(agent_id, tier=tier)

    return {
        "new_key": new_key_info["key"],
        "tier": tier,
        "agent_id": agent_id,
        "revoked": revoked,
    }


# ---------------------------------------------------------------------------
# List API Keys (P1)
# ---------------------------------------------------------------------------


async def _list_api_keys(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """List all API keys for an agent (returns truncated key_hash for security)."""
    agent_id = params["agent_id"]
    keys = await ctx.key_manager.get_agent_keys(agent_id)

    sanitized_keys = []
    for k in keys:
        sanitized_keys.append(
            {
                "key_hash_prefix": k["key_hash"][:8],
                "tier": k["tier"],
                "scopes": k.get("scopes", ["read", "write"]),
                "created_at": k["created_at"],
                "revoked": bool(k["revoked"]),
            }
        )

    return {"keys": sanitized_keys}


# ---------------------------------------------------------------------------
# Revoke API Key (P1)
# ---------------------------------------------------------------------------


async def _revoke_api_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Soft-delete (revoke) an API key by key_hash prefix for the given agent."""
    agent_id = params["agent_id"]
    key_hash_prefix = params["key_hash_prefix"]

    # Look up all keys for the agent and find one matching the prefix
    keys = await ctx.key_manager.get_agent_keys(agent_id)

    for k in keys:
        if k["key_hash"].startswith(key_hash_prefix) and not k["revoked"]:
            revoked = await ctx.key_manager.storage.revoke_key(k["key_hash"])
            return {"revoked": revoked, "key_hash_prefix": key_hash_prefix}

    return {"revoked": False, "key_hash_prefix": key_hash_prefix}


# ---------------------------------------------------------------------------
# Self-service API Key Creation (P2-17)
# ---------------------------------------------------------------------------


async def _create_api_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Create a new API key for an agent (self-service)."""
    agent_id = params["agent_id"]
    tier = params.get("tier", "free")

    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return {
        "key": key_info["key"],
        "agent_id": agent_id,
        "tier": tier,
        "created_at": key_info["created_at"],
    }


# ---------------------------------------------------------------------------
# Database Security
# ---------------------------------------------------------------------------


_DB_DSN_MAP = {
    "billing": "BILLING_DSN",
    "paywall": "PAYWALL_DSN",
    "payments": "PAYMENTS_DSN",
    "marketplace": "MARKETPLACE_DSN",
    "trust": "TRUST_DSN",
    "identity": "IDENTITY_DSN",
    "event_bus": "EVENT_BUS_DSN",
    "webhooks": "WEBHOOK_DSN",
    "disputes": "DISPUTE_DSN",
    "messaging": "MESSAGING_DSN",
}


def _resolve_db_path(db_name: str) -> str:
    """Resolve a logical database name to its file path."""
    import os

    env_var = _DB_DSN_MAP.get(db_name)
    if not env_var:
        from gateway.src.tool_errors import ToolValidationError

        raise ToolValidationError(f"Unknown database: {db_name}")
    dsn = os.environ.get(env_var, "")
    if not dsn:
        raise ValueError(f"DSN not configured for {db_name} (env: {env_var})")
    return dsn.replace("sqlite:///", "")


async def _backup_database(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os
    from datetime import datetime

    from shared_src.db_security import backup_database, encrypt_backup

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    backup_dir = os.path.join(data_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"{db_name}_{ts}.db")

    meta = await backup_database(db_path, dest)

    if params.get("encrypt"):
        enc_dest = dest + ".enc"
        enc_meta = await encrypt_backup(dest, enc_dest)
        os.unlink(dest)
        meta["path"] = enc_dest
        meta["size_bytes"] = enc_meta["size_bytes"]
        meta["key"] = enc_meta["key"]
        meta["encrypted"] = True

    return meta


async def _restore_database(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os

    from shared_src.db_security import decrypt_backup, restore_database

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    backup_path = params["backup_path"]

    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    source = backup_path
    if params.get("key"):
        dec_path = backup_path + ".dec"
        await decrypt_backup(backup_path, dec_path, params["key"])
        source = dec_path

    meta = await restore_database(source, db_path)

    if source != backup_path and os.path.exists(source):
        os.unlink(source)

    return meta


async def _check_db_integrity(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    from shared_src.db_security import integrity_check

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    return await integrity_check(db_path)


async def _list_backups(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os

    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    backup_dir = os.path.join(data_dir, "backups")

    if not os.path.isdir(backup_dir):
        return {"backups": []}

    backups = []
    for fname in sorted(os.listdir(backup_dir)):
        fpath = os.path.join(backup_dir, fname)
        if os.path.isfile(fpath):
            backups.append(
                {
                    "filename": fname,
                    "path": fpath,
                    "size_bytes": os.path.getsize(fpath),
                }
            )
    return {"backups": backups}
