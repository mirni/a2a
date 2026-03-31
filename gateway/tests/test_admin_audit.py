"""Tests for admin audit trail.

Verifies that admin operations (resolve_dispute, freeze_wallet, unfreeze_wallet,
get_global_audit_log) are logged to a dedicated admin_audit_log table with:
- admin agent_id
- tool_name
- params (sanitized -- no secrets)
- timestamp
- client IP
- result status (success/denied/error)
- result_summary

Also verifies:
- Non-admin tool calls do NOT create admin audit records
- Failed admin tool calls (denied) are also logged
- Params are sanitized to strip secrets/tokens/API keys
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    """Create a wallet + API key for an agent. Returns the raw API key."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _create_admin_agent(app, agent_id: str = "admin-agent") -> str:
    """Create an admin-tier agent. Returns the raw API key."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=10000.0, signup_bonus=False)

    raw_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(
        key_hash=key_hash,
        agent_id=agent_id,
        tier="admin",
    )
    return raw_key


async def _get_admin_audit_records(app) -> list[dict[str, Any]]:
    """Retrieve all admin audit log records from the billing DB."""
    from gateway.src.admin_audit import get_admin_audit_log

    db = app.state.ctx.tracker.storage.db
    return await get_admin_audit_log(db)


# ---------------------------------------------------------------------------
# 1. Admin tool call creates audit record
# ---------------------------------------------------------------------------


class TestAdminAuditRecordCreation:
    """Admin tool calls must create an admin audit record."""

    async def test_successful_admin_tool_creates_audit_record(self, client, app):
        """When an admin calls freeze_wallet, an audit record is created."""
        admin_key = await _create_admin_agent(app, "audit-admin-1")
        # Create target wallet
        await _create_agent(app, "target-freeze-1")

        resp = await client.post(
            "/v1/execute",
            json={"tool": "freeze_wallet", "params": {"agent_id": "target-freeze-1"}},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 200

        records = await _get_admin_audit_records(app)
        assert len(records) >= 1

        record = records[-1]
        assert record["agent_id"] == "audit-admin-1"
        assert record["tool_name"] == "freeze_wallet"
        assert record["status"] == "success"
        assert record["timestamp"] > 0
        assert record["client_ip"] is not None

    async def test_audit_record_includes_params(self, client, app):
        """Audit record should include the params (sanitized) as JSON."""
        admin_key = await _create_admin_agent(app, "audit-admin-2")
        await _create_agent(app, "target-freeze-2")

        await client.post(
            "/v1/execute",
            json={"tool": "freeze_wallet", "params": {"agent_id": "target-freeze-2"}},
            headers={"Authorization": f"Bearer {admin_key}"},
        )

        records = await _get_admin_audit_records(app)
        record = records[-1]
        import json

        params = json.loads(record["params_json"])
        assert params["agent_id"] == "target-freeze-2"

    async def test_audit_record_includes_result_summary(self, client, app):
        """Audit record should include a result_summary."""
        admin_key = await _create_admin_agent(app, "audit-admin-3")
        await _create_agent(app, "target-freeze-3")

        await client.post(
            "/v1/execute",
            json={"tool": "freeze_wallet", "params": {"agent_id": "target-freeze-3"}},
            headers={"Authorization": f"Bearer {admin_key}"},
        )

        records = await _get_admin_audit_records(app)
        record = records[-1]
        assert record["result_summary"] is not None


# ---------------------------------------------------------------------------
# 2. Non-admin tool calls do NOT create admin audit records
# ---------------------------------------------------------------------------


class TestNonAdminToolsNotLogged:
    """Non-admin tool calls must NOT create admin audit records."""

    async def test_regular_tool_does_not_create_admin_audit(self, client, app):
        """get_balance (not admin-only) should NOT create an admin audit record."""
        key = await _create_agent(app, "regular-agent-1")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "regular-agent-1"}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

        records = await _get_admin_audit_records(app)
        admin_tool_records = [r for r in records if r["tool_name"] == "get_balance"]
        assert len(admin_tool_records) == 0


# ---------------------------------------------------------------------------
# 3. Denied admin tool calls are also logged
# ---------------------------------------------------------------------------


class TestDeniedAdminCallsLogged:
    """Failed admin tool attempts (non-admin calling admin tool) must be logged."""

    async def test_denied_admin_tool_creates_audit_record(self, client, app):
        """A non-admin calling freeze_wallet on their own wallet should be denied AND logged.

        We use agent_id matching the caller so the ownership check passes,
        but the admin-only check still blocks the non-admin caller.
        """
        key = await _create_agent(app, "non-admin-1")

        resp = await client.post(
            "/v1/execute",
            json={"tool": "freeze_wallet", "params": {"agent_id": "non-admin-1"}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

        records = await _get_admin_audit_records(app)
        denied_records = [r for r in records if r["status"] == "denied"]
        assert len(denied_records) >= 1

        record = denied_records[-1]
        assert record["agent_id"] == "non-admin-1"
        assert record["tool_name"] == "freeze_wallet"
        assert record["status"] == "denied"


# ---------------------------------------------------------------------------
# 4. Param sanitization -- secrets stripped
# ---------------------------------------------------------------------------


class TestParamSanitization:
    """Params must be sanitized before logging to strip secrets."""

    def test_sanitize_strips_secret_keys(self):
        """sanitize_params should strip common secret field names."""
        from gateway.src.admin_audit import sanitize_params

        params = {
            "agent_id": "alice",
            "api_key": "sk-secret-12345",
            "token": "jwt-abc123",
            "secret": "my-secret",
            "password": "p@ssw0rd",
            "authorization": "Bearer xyz",
            "normal_field": "keep-this",
        }
        sanitized = sanitize_params(params)
        assert sanitized["agent_id"] == "alice"
        assert sanitized["normal_field"] == "keep-this"
        assert sanitized["api_key"] == "***REDACTED***"
        assert sanitized["token"] == "***REDACTED***"
        assert sanitized["secret"] == "***REDACTED***"
        assert sanitized["password"] == "***REDACTED***"
        assert sanitized["authorization"] == "***REDACTED***"

    def test_sanitize_strips_caller_internal_fields(self):
        """sanitize_params should strip internal _caller_* fields."""
        from gateway.src.admin_audit import sanitize_params

        params = {
            "agent_id": "alice",
            "_caller_agent_id": "admin-1",
            "_caller_tier": "admin",
        }
        sanitized = sanitize_params(params)
        assert sanitized["agent_id"] == "alice"
        assert "_caller_agent_id" not in sanitized
        assert "_caller_tier" not in sanitized

    def test_sanitize_handles_empty_params(self):
        """sanitize_params should handle empty dict."""
        from gateway.src.admin_audit import sanitize_params

        assert sanitize_params({}) == {}

    def test_sanitize_handles_nested_secrets(self):
        """sanitize_params should handle nested dicts with secret keys."""
        from gateway.src.admin_audit import sanitize_params

        params = {
            "config": {"api_key": "secret-key", "name": "test"},
            "agent_id": "bob",
        }
        sanitized = sanitize_params(params)
        assert sanitized["agent_id"] == "bob"
        # nested dict should also be sanitized
        assert sanitized["config"]["api_key"] == "***REDACTED***"
        assert sanitized["config"]["name"] == "test"


# ---------------------------------------------------------------------------
# 5. Admin audit log table schema
# ---------------------------------------------------------------------------


class TestAdminAuditSchema:
    """The admin_audit_log table must have the expected columns."""

    async def test_table_exists_after_app_start(self, app):
        """admin_audit_log table should exist after app startup."""
        db = app.state.ctx.tracker.storage.db
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_audit_log'")
        row = await cursor.fetchone()
        assert row is not None, "admin_audit_log table should exist"

    async def test_table_has_expected_columns(self, app):
        """admin_audit_log table should have all required columns."""
        db = app.state.ctx.tracker.storage.db
        cursor = await db.execute("PRAGMA table_info(admin_audit_log)")
        rows = await cursor.fetchall()
        column_names = {row[1] for row in rows}
        expected = {
            "id",
            "timestamp",
            "agent_id",
            "tool_name",
            "params_json",
            "client_ip",
            "status",
            "result_summary",
        }
        assert expected.issubset(column_names), f"Missing columns: {expected - column_names}"


# ---------------------------------------------------------------------------
# 6. log_admin_operation function
# ---------------------------------------------------------------------------


class TestLogAdminOperation:
    """Unit tests for the log_admin_operation function."""

    async def test_log_admin_operation_writes_record(self, app):
        """log_admin_operation should write a record to admin_audit_log."""
        from gateway.src.admin_audit import get_admin_audit_log, log_admin_operation

        db = app.state.ctx.tracker.storage.db
        await log_admin_operation(
            db=db,
            agent_id="test-admin",
            tool_name="freeze_wallet",
            params={"agent_id": "target"},
            client_ip="127.0.0.1",
            status="success",
            result_summary="Wallet frozen",
        )

        records = await get_admin_audit_log(db)
        assert len(records) >= 1
        record = records[-1]
        assert record["agent_id"] == "test-admin"
        assert record["tool_name"] == "freeze_wallet"
        assert record["client_ip"] == "127.0.0.1"
        assert record["status"] == "success"
        assert record["result_summary"] == "Wallet frozen"

    async def test_log_admin_operation_sanitizes_params(self, app):
        """log_admin_operation should sanitize params before writing."""
        from gateway.src.admin_audit import get_admin_audit_log, log_admin_operation

        db = app.state.ctx.tracker.storage.db
        await log_admin_operation(
            db=db,
            agent_id="test-admin",
            tool_name="freeze_wallet",
            params={"agent_id": "target", "api_key": "secret-123"},
            client_ip="10.0.0.1",
            status="success",
            result_summary="OK",
        )

        records = await get_admin_audit_log(db)
        record = records[-1]
        import json

        params = json.loads(record["params_json"])
        assert params["api_key"] == "***REDACTED***"
        assert params["agent_id"] == "target"
