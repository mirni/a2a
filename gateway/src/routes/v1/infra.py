"""Infrastructure REST endpoints — /v1/infra/."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from gateway.src.deps.tool_context import ToolContext, check_ownership, finalize_response, require_tool
from gateway.src.errors import handle_product_exception
from gateway.src.tools.infrastructure import (
    _backup_database,
    _check_db_integrity,
    _create_api_key,
    _delete_webhook,
    _get_event_schema,
    _get_events,
    _get_global_audit_log,
    _get_webhook_deliveries,
    _list_api_keys,
    _list_backups,
    _list_webhooks,
    _publish_event,
    _register_event_schema,
    _register_webhook,
    _restore_database,
    _revoke_api_key,
    _rotate_key,
    _test_webhook,
)

router = APIRouter(prefix="/v1/infra", tags=["infra"])


# ---------------------------------------------------------------------------
# Pydantic request models (extra="forbid")
# ---------------------------------------------------------------------------


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: str = "free"


class RevokeApiKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_hash_prefix: str


class RotateKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_key: str


class RegisterWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    event_types: list[str]
    secret: str
    filter_agent_ids: list[str] | None = None


class PublishEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    source: str
    payload: dict[str, Any] | None = None


class RegisterEventSchemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str
    schema_def: dict[str, Any] = Field(alias="schema")


class BackupDatabaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encrypt: bool = False


class RestoreDatabaseRequest(BaseModel):
    """Restore from a previous backup.

    Either ``filename`` (preferred — matches what ``list_backups`` /
    ``backup_database`` now return) or ``backup_path`` (legacy — full
    path inside the backup dir) may be provided. ``filename`` is
    resolved server-side against ``A2A_DATA_DIR/backups`` so callers
    never need to know the absolute path.
    """

    model_config = ConfigDict(extra="forbid")
    backup_path: str | None = None
    filename: str | None = None
    key: str | None = None
    key_id: str | None = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _inject_caller(tc: ToolContext, params: dict[str, Any]) -> dict[str, Any]:
    params["_caller_agent_id"] = tc.agent_id
    params["_caller_tier"] = tc.agent_tier
    return params


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------


@router.post("/keys")
async def create_api_key(
    body: CreateApiKeyRequest,
    tc: ToolContext = Depends(require_tool("create_api_key")),
):
    params = _inject_caller(
        tc,
        {"agent_id": tc.agent_id, "tier": body.tier},
    )
    await check_ownership(tc, params)
    try:
        result = await _create_api_key(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result, status_code=201)


@router.get("/keys")
async def list_api_keys(
    tc: ToolContext = Depends(require_tool("list_api_keys")),
):
    params = _inject_caller(tc, {"agent_id": tc.agent_id})
    await check_ownership(tc, params)
    result = await _list_api_keys(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/keys/revoke")
async def revoke_api_key(
    body: RevokeApiKeyRequest,
    tc: ToolContext = Depends(require_tool("revoke_api_key")),
):
    params = _inject_caller(
        tc,
        {"agent_id": tc.agent_id, "key_hash_prefix": body.key_hash_prefix},
    )
    await check_ownership(tc, params)
    result = await _revoke_api_key(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/keys/rotate")
async def rotate_key(
    body: RotateKeyRequest,
    x_rotate_confirmation: str | None = Header(default=None, alias="X-Rotate-Confirmation"),
    tc: ToolContext = Depends(require_tool("rotate_key")),
):
    # v1.2.2 audit HIGH-7: key rotation was dangerously easy to trigger.
    # Two consecutive auditor agents accidentally rotated the production
    # PRO key during schema probing. Require an explicit confirmation
    # header so rotation cannot happen on a stray POST.
    if x_rotate_confirmation != "confirm":
        return JSONResponse(
            status_code=428,
            content={
                "type": "https://api.greenhelix.net/errors/rotate-confirmation-required",
                "title": "Rotate confirmation required",
                "status": 428,
                "detail": (
                    "Key rotation is a destructive action. Include the "
                    "header 'X-Rotate-Confirmation: confirm' to proceed. "
                    "The old key remains valid for a 300s grace window "
                    "after a successful rotation."
                ),
                "instance": "/v1/infra/keys/rotate",
            },
        )
    params = _inject_caller(tc, {"current_key": body.current_key})
    await check_ownership(tc, params)
    try:
        result = await _rotate_key(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


@router.post("/webhooks")
async def register_webhook(
    body: RegisterWebhookRequest,
    tc: ToolContext = Depends(require_tool("register_webhook")),
):
    params = _inject_caller(
        tc,
        {
            "agent_id": tc.agent_id,
            "url": body.url,
            "event_types": body.event_types,
            "secret": body.secret,
            "filter_agent_ids": body.filter_agent_ids,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _register_webhook(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    location = f"/v1/infra/webhooks/{result.get('id', '')}"
    return await finalize_response(tc, result, status_code=201, location=location)


@router.get("/webhooks")
async def list_webhooks(
    tc: ToolContext = Depends(require_tool("list_webhooks")),
):
    params = _inject_caller(tc, {"agent_id": tc.agent_id})
    await check_ownership(tc, params)
    result = await _list_webhooks(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    tc: ToolContext = Depends(require_tool("test_webhook")),
):
    params = _inject_caller(tc, {"webhook_id": webhook_id})
    await check_ownership(tc, params)
    try:
        result = await _test_webhook(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook(
    webhook_id: str,
    tc: ToolContext = Depends(require_tool("delete_webhook")),
):
    params = _inject_caller(tc, {"webhook_id": webhook_id})
    await check_ownership(tc, params)
    try:
        result = await _delete_webhook(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/webhooks/{webhook_id}/deliveries")
async def get_webhook_deliveries(
    webhook_id: str,
    limit: int = 50,
    offset: int = 0,
    tc: ToolContext = Depends(require_tool("get_webhook_deliveries")),
):
    params = _inject_caller(
        tc,
        {"webhook_id": webhook_id, "limit": limit, "offset": offset},
    )
    await check_ownership(tc, params)
    try:
        result = await _get_webhook_deliveries(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@router.post("/events/schemas")
async def register_event_schema(
    body: RegisterEventSchemaRequest,
    tc: ToolContext = Depends(require_tool("register_event_schema")),
):
    params = _inject_caller(
        tc,
        {"event_type": body.event_type, "schema": body.schema_def},
    )
    await check_ownership(tc, params)
    try:
        result = await _register_event_schema(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/events")
async def publish_event(
    body: PublishEventRequest,
    tc: ToolContext = Depends(require_tool("publish_event")),
):
    params = _inject_caller(
        tc,
        {
            "event_type": body.event_type,
            "source": body.source,
            "payload": body.payload or {},
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _publish_event(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/events/schemas/{event_type:path}")
async def get_event_schema(
    event_type: str,
    tc: ToolContext = Depends(require_tool("get_event_schema")),
):
    params = _inject_caller(tc, {"event_type": event_type})
    await check_ownership(tc, params)
    result = await _get_event_schema(tc.ctx, params)
    return await finalize_response(tc, result)


@router.get("/events")
async def get_events(
    event_type: str | None = None,
    since_id: int = 0,
    limit: int = 100,
    tc: ToolContext = Depends(require_tool("get_events")),
):
    params = _inject_caller(
        tc,
        {"event_type": event_type, "since_id": since_id, "limit": limit},
    )
    await check_ownership(tc, params)
    result = await _get_events(tc.ctx, params)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Admin / Audit
# ---------------------------------------------------------------------------


@router.get("/audit-log")
async def get_global_audit_log(
    since: float | None = None,
    limit: int = 100,
    tc: ToolContext = Depends(require_tool("get_global_audit_log")),
):
    params = _inject_caller(tc, {"since": since, "limit": limit})
    await check_ownership(tc, params)
    result = await _get_global_audit_log(tc.ctx, params)
    return await finalize_response(tc, result)


# ---------------------------------------------------------------------------
# Database Operations
# ---------------------------------------------------------------------------


@router.get("/databases/backups")
async def list_backups(
    tc: ToolContext = Depends(require_tool("list_backups")),
):
    params = _inject_caller(tc, {})
    await check_ownership(tc, params)
    result = await _list_backups(tc.ctx, params)
    return await finalize_response(tc, result)


@router.post("/databases/{database}/backup")
async def backup_database(
    database: str,
    body: BackupDatabaseRequest | None = None,
    tc: ToolContext = Depends(require_tool("backup_database")),
):
    params = _inject_caller(
        tc,
        {"database": database, "encrypt": body.encrypt if body else False},
    )
    await check_ownership(tc, params)
    try:
        result = await _backup_database(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.post("/databases/{database}/restore")
async def restore_database(
    database: str,
    body: RestoreDatabaseRequest,
    tc: ToolContext = Depends(require_tool("restore_database")),
):
    params = _inject_caller(
        tc,
        {
            "database": database,
            "backup_path": body.backup_path,
            "filename": body.filename,
            "key": body.key,
            "key_id": body.key_id,
        },
    )
    await check_ownership(tc, params)
    try:
        result = await _restore_database(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)


@router.get("/databases/{database}/integrity")
async def check_db_integrity(
    database: str,
    tc: ToolContext = Depends(require_tool("check_db_integrity")),
):
    params = _inject_caller(tc, {"database": database})
    await check_ownership(tc, params)
    try:
        result = await _check_db_integrity(tc.ctx, params)
    except Exception as exc:
        return await handle_product_exception(tc.request, exc)
    return await finalize_response(tc, result)
