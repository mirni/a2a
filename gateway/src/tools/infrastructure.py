"""Infrastructure tool functions: events, webhooks, keys, DB ops."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tools._pagination import _paginate

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
    from gateway.src.tool_errors import ToolValidationError
    from gateway.src.url_validator import validate_webhook_url

    url = params["url"]
    url_error = validate_webhook_url(url)
    if url_error:
        raise ToolValidationError(f"Invalid webhook URL: {url_error}")

    secret = params.get("secret", "")
    if not secret:
        raise ToolValidationError("Webhook 'secret' is required and must be non-empty for HMAC signature verification")
    result = await ctx.webhook_manager.register(
        agent_id=params["agent_id"],
        url=url,
        event_types=params["event_types"],
        secret=secret,
        filter_agent_ids=params.get("filter_agent_ids"),
    )
    return result


async def _list_webhooks(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    webhooks = await ctx.webhook_manager.list_webhooks(params["agent_id"])
    if params.get("paginate"):
        return _paginate(webhooks, params)
    return {"webhooks": webhooks}


async def _check_webhook_ownership(ctx: AppContext, params: dict[str, Any], webhook_id: str) -> None:
    """Verify the caller owns the webhook. Raises ToolForbiddenError on mismatch."""
    from gateway.src.tool_errors import ToolForbiddenError

    caller = params.get("_caller_agent_id")
    if not caller:
        return  # no caller info (e.g. tests without execute route)

    webhook = await ctx.webhook_manager.get_webhook(webhook_id)
    if webhook is None:
        from gateway.src.tool_errors import ToolNotFoundError

        raise ToolNotFoundError(f"Webhook not found: {webhook_id}")

    if webhook["agent_id"] != caller:
        raise ToolForbiddenError("Forbidden: you do not have access to this resource")


async def _delete_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    webhook_id = params["webhook_id"]
    await _check_webhook_ownership(ctx, params, webhook_id)
    deleted = await ctx.webhook_manager.delete_webhook(webhook_id)
    return {"deleted": deleted}


async def _get_webhook_deliveries(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    webhook_id = params["webhook_id"]
    await _check_webhook_ownership(ctx, params, webhook_id)
    deliveries = await ctx.webhook_manager.get_delivery_history(
        webhook_id=webhook_id,
        limit=params.get("limit", 50),
        offset=params.get("offset", 0),
    )
    return {"deliveries": deliveries}


# ---------------------------------------------------------------------------
# Webhook Test/Ping (P2-15)
# ---------------------------------------------------------------------------


async def _test_webhook(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Send a test.ping event to a registered webhook and return the delivery result."""
    from gateway.src.tool_errors import ToolNotFoundError

    webhook_id = params["webhook_id"]
    await _check_webhook_ownership(ctx, params, webhook_id)
    wm = ctx.webhook_manager

    try:
        return await wm.send_test_ping(webhook_id)
    except LookupError:
        raise ToolNotFoundError(f"Webhook not found: {webhook_id}") from None


# ---------------------------------------------------------------------------
# Key Rotation
# ---------------------------------------------------------------------------


async def _rotate_key(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Revoke current key and create a new one with the same tier.

    Uses BEGIN IMMEDIATE so revoke + create is atomic — no window where
    the old key is revoked but the new one doesn't exist yet.
    """
    current_key = params["current_key"]
    key_info = await ctx.key_manager.validate_key(current_key)
    agent_id = key_info["agent_id"]
    tier = key_info["tier"]

    db = ctx.key_manager.storage.db
    await db.execute("BEGIN IMMEDIATE")
    try:
        revoked = await ctx.key_manager.revoke_key(current_key)
        new_key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

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

    if params.get("paginate"):
        return _paginate(sanitized_keys, params)

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
    """Create a new API key for an agent (self-service).

    Security: the requested tier must not exceed the caller's own tier.
    """
    from gateway.src.tool_errors import ToolForbiddenError

    agent_id = params["agent_id"]
    requested_tier = params.get("tier", "free")

    # Prevent tier escalation: caller cannot create keys above their own tier.
    caller_tier = params.get("_caller_tier", "free")
    _TIER_RANK = {"free": 0, "starter": 1, "pro": 2, "admin": 3}
    caller_rank = _TIER_RANK.get(caller_tier, 0)
    requested_rank = _TIER_RANK.get(requested_tier, 99)

    if requested_rank > caller_rank:
        raise ToolForbiddenError(
            f"Tier escalation denied: your tier '{caller_tier}' cannot create '{requested_tier}' keys"
        )

    key_info = await ctx.key_manager.create_key(agent_id, tier=requested_tier)
    return {
        "key": key_info["key"],
        "agent_id": agent_id,
        "tier": requested_tier,
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
    import hashlib
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
        meta["encrypted"] = True

        # Store key server-side instead of returning it in the response.
        # The key is written to a restricted file and referenced by key_id.
        key_id = hashlib.sha256(enc_meta["key"].encode()).hexdigest()[:16]
        keys_dir = os.path.join(data_dir, "backup_keys")
        os.makedirs(keys_dir, exist_ok=True)
        key_path = os.path.join(keys_dir, f"{key_id}.key")
        with open(key_path, "w") as f:
            f.write(enc_meta["key"])
        os.chmod(key_path, 0o600)
        meta["key_id"] = key_id

    return meta


async def _restore_database(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    import os

    from shared_src.db_security import decrypt_backup, restore_database

    from gateway.src.tool_errors import ToolValidationError

    db_name = params["database"]
    db_path = _resolve_db_path(db_name)
    backup_path = params["backup_path"]

    # Security: prevent path traversal attacks
    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    backup_dir = os.path.realpath(os.path.join(data_dir, "backups"))
    real_backup = os.path.realpath(backup_path)
    if not real_backup.startswith(backup_dir + os.sep) and real_backup != backup_dir:
        raise ToolValidationError(
            "Invalid backup_path: path traversal detected. Backup files must reside in the backups directory."
        )

    if not os.path.isfile(real_backup):
        raise FileNotFoundError(f"Backup not found: {backup_path}")

    source = backup_path
    key = params.get("key")
    # Support key_id-based retrieval of stored encryption keys
    if not key and params.get("key_id"):
        key_path = os.path.join(data_dir, "backup_keys", f"{params['key_id']}.key")
        if os.path.exists(key_path):
            with open(key_path) as f:
                key = f.read().strip()

    if key:
        dec_path = backup_path + ".dec"
        await decrypt_backup(backup_path, dec_path, key)
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
