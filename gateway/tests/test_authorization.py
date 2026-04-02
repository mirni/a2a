"""Tests for agent-scoped authorization guard.

Verifies that API key holders can only operate on resources they own:
- agent_id param must match caller's agent_id
- payer param must match caller's agent_id
- sender param must match caller's agent_id
- admin tier bypasses all checks
- tools without ownership params are unrestricted
"""

from __future__ import annotations

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
    """Create an admin-tier agent. Returns the raw API key.

    Admin is not a standard TierName, so we insert directly into storage
    bypassing KeyManager.create_key's tier validation.
    """
    import hashlib
    import secrets

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


# ---------------------------------------------------------------------------
# 1. agent_id param — own resources
# ---------------------------------------------------------------------------


class TestAgentIdOwnership:
    """Tools that take an agent_id param must match the caller's agent_id."""

    async def test_agent_can_access_own_resources(self, client, app):
        """200: agent_id in params matches the caller's agent_id."""
        key = await _create_agent(app, "alice")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "alice"}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_agent_cannot_access_other_agent_resources(self, client, app):
        """403: agent_id in params does NOT match the caller's agent_id."""
        key_alice = await _create_agent(app, "alice")
        await _create_agent(app, "bob")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "bob"}},
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        body = resp.json()
        assert body["type"].endswith("/forbidden")
        assert "bob" not in body["detail"]

    async def test_ownership_check_on_deposit(self, client, app):
        """403: cannot deposit into another agent's wallet."""
        key_alice = await _create_agent(app, "alice-dep")
        await _create_agent(app, "bob-dep")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "deposit",
                "params": {"agent_id": "bob-dep", "amount": 100},
            },
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")

    async def test_ownership_check_on_get_usage_summary(self, client, app):
        """403: cannot view another agent's usage."""
        key_alice = await _create_agent(app, "alice-usage")
        await _create_agent(app, "bob-usage")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_usage_summary",
                "params": {"agent_id": "bob-usage"},
            },
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")


# ---------------------------------------------------------------------------
# 2. payer param — payment tools
# ---------------------------------------------------------------------------


class TestPayerOwnership:
    """Tools that take a payer param must match the caller's agent_id."""

    async def test_payer_matches_caller(self, client, app):
        """200: payer == caller's agent_id (create_intent)."""
        key = await _create_agent(app, "payer-ok", balance=5000.0)
        await _create_agent(app, "payee-ok")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "payer-ok",
                    "payee": "payee-ok",
                    "amount": 10.0,
                    "description": "test payment",
                },
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        # Should not be 403 — may be 200 or other error, but not ownership denial
        assert resp.status_code != 403

    async def test_payer_mismatch_is_forbidden(self, client, app):
        """403: payer != caller's agent_id."""
        key_alice = await _create_agent(app, "alice-pay")
        await _create_agent(app, "bob-pay")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "bob-pay",
                    "payee": "alice-pay",
                    "amount": 10.0,
                    "description": "sneaky payment",
                },
            },
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")

    async def test_escrow_payer_mismatch(self, client, app):
        """403: cannot create escrow as someone else."""
        key_alice = await _create_agent(app, "alice-esc")
        await _create_agent(app, "bob-esc")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_escrow",
                "params": {
                    "payer": "bob-esc",
                    "payee": "alice-esc",
                    "amount": 50.0,
                    "description": "escrow test",
                },
            },
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")


# ---------------------------------------------------------------------------
# 3. sender param — messaging tools
# ---------------------------------------------------------------------------


class TestSenderOwnership:
    """Tools that take a sender param must match the caller's agent_id."""

    async def test_sender_matches_caller(self, client, app):
        """200: sender == caller's agent_id."""
        key = await _create_agent(app, "sender-ok")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "send_message",
                "params": {
                    "sender": "sender-ok",
                    "recipient": "someone",
                    "message_type": "text",
                    "subject": "hi",
                    "body": "hello",
                },
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        # Should not be 403
        assert resp.status_code != 403

    async def test_sender_mismatch_is_forbidden(self, client, app):
        """403: sender != caller's agent_id."""
        key_alice = await _create_agent(app, "alice-msg")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "send_message",
                "params": {
                    "sender": "bob-msg",
                    "recipient": "someone",
                    "message_type": "text",
                    "subject": "hi",
                    "body": "hello",
                },
            },
            headers={"Authorization": f"Bearer {key_alice}"},
        )
        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")


# ---------------------------------------------------------------------------
# 4. Admin bypass
# ---------------------------------------------------------------------------


class TestAdminBypass:
    """Admin-tier keys should bypass all ownership checks."""

    async def test_admin_can_access_any_agent_resources(self, client, app):
        """200: admin key can get_balance for any agent."""
        admin_key = await _create_admin_agent(app, "admin-1")
        await _create_agent(app, "target-agent")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "target-agent"}},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code == 200

    async def test_admin_can_create_intent_for_any_payer(self, client, app):
        """200: admin key can create_intent with any payer."""
        admin_key = await _create_admin_agent(app, "admin-2")
        await _create_agent(app, "payer-x", balance=5000.0)
        await _create_agent(app, "payee-x")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "payer-x",
                    "payee": "payee-x",
                    "amount": 10.0,
                    "description": "admin override",
                },
            },
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        # Not 403 — admin bypasses ownership check
        assert resp.status_code != 403

    async def test_admin_can_send_message_as_any_sender(self, client, app):
        """200: admin key can send_message with any sender."""
        admin_key = await _create_admin_agent(app, "admin-3")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "send_message",
                "params": {
                    "sender": "someone-else",
                    "recipient": "anyone",
                    "message_type": "text",
                    "subject": "admin msg",
                    "body": "hello from admin",
                },
            },
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# 5. Tools without ownership params
# ---------------------------------------------------------------------------


class TestNoOwnershipParam:
    """Tools without agent_id/payer/sender should work for any authenticated caller."""

    async def test_search_services_no_ownership(self, client, app):
        """200: search_services has no ownership param — any caller can use it."""
        key = await _create_agent(app, "searcher")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "search_services",
                "params": {"query": "test"},
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        # Should not be 403
        assert resp.status_code != 403

    async def test_capture_intent_no_ownership(self, client, app):
        """capture_intent has no ownership-relevant param — any caller works."""
        key = await _create_agent(app, "capturer")
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "capture_intent",
                "params": {"intent_id": "nonexistent-intent"},
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        # May be 404 (intent not found) but NOT 403 (ownership)
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# 6. Unit tests for the authorization function itself
# ---------------------------------------------------------------------------


class TestAuthorizationGuard:
    """Direct unit tests for the check_ownership_authorization function."""

    def test_matching_agent_id_returns_none(self):
        """No error when agent_id matches caller."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"agent_id": "alice"},
        )
        assert result is None

    def test_mismatched_agent_id_returns_error(self):
        """Returns error tuple when agent_id does not match."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"agent_id": "bob"},
        )
        assert result is not None
        assert result[0] == 403

    def test_mismatched_payer_returns_error(self):
        """Returns error tuple when payer does not match."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"payer": "bob", "payee": "alice", "amount": 10},
        )
        assert result is not None
        assert result[0] == 403

    def test_mismatched_sender_returns_error(self):
        """Returns error tuple when sender does not match."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"sender": "bob", "recipient": "alice"},
        )
        assert result is not None
        assert result[0] == 403

    def test_admin_bypasses_agent_id_check(self):
        """Admin tier bypasses ownership checks."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="admin-agent",
            caller_tier="admin",
            params={"agent_id": "someone-else"},
        )
        assert result is None

    def test_admin_bypasses_payer_check(self):
        """Admin tier bypasses payer ownership checks."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="admin-agent",
            caller_tier="admin",
            params={"payer": "someone-else", "payee": "x", "amount": 10},
        )
        assert result is None

    def test_admin_bypasses_sender_check(self):
        """Admin tier bypasses sender ownership checks."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="admin-agent",
            caller_tier="admin",
            params={"sender": "someone-else"},
        )
        assert result is None

    def test_no_ownership_param_returns_none(self):
        """No error when params have no ownership-relevant fields."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"query": "test", "limit": 10},
        )
        assert result is None

    def test_empty_params_returns_none(self):
        """No error for empty params dict."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={},
        )
        assert result is None

    def test_multiple_ownership_fields_all_checked(self):
        """If both agent_id and payer are present, both must match."""
        from gateway.src.authorization import check_ownership_authorization

        # agent_id matches but payer doesn't
        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"agent_id": "alice", "payer": "bob"},
        )
        assert result is not None
        assert result[0] == 403

    def test_error_message_does_not_leak_values(self):
        """Error message must NOT echo user-supplied input or caller agent_id."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="alice",
            caller_tier="free",
            params={"agent_id": "bob"},
        )
        assert result is not None
        status, message, code = result
        assert "bob" not in message
        assert "alice" not in message
        assert code == "forbidden"

    def test_error_message_does_not_reflect_injection(self):
        """Attacker-supplied SQL/XSS payloads must not appear in error."""
        from gateway.src.authorization import check_ownership_authorization

        result = check_ownership_authorization(
            caller_agent_id="victim",
            caller_tier="free",
            params={"agent_id": "'; DROP TABLE wallets;--"},
        )
        assert result is not None
        status, message, code = result
        assert "DROP TABLE" not in message
        assert "victim" not in message


# ---------------------------------------------------------------------------
# 7. Admin-only tools — non-admin gets 403
# ---------------------------------------------------------------------------


class TestAdminOnlyTools:
    """Database admin tools must require admin tier."""

    ADMIN_ONLY_DB_TOOLS = [
        "backup_database",
        "restore_database",
        "check_db_integrity",
        "list_backups",
    ]

    def test_admin_only_tools_in_frozenset(self):
        """All DB admin tools must be in ADMIN_ONLY_TOOLS."""
        from gateway.src.authorization import ADMIN_ONLY_TOOLS

        for tool in self.ADMIN_ONLY_DB_TOOLS:
            assert tool in ADMIN_ONLY_TOOLS, f"{tool} missing from ADMIN_ONLY_TOOLS"

    def test_admin_only_tools_count(self):
        """ADMIN_ONLY_TOOLS should have at least 8 entries."""
        from gateway.src.authorization import ADMIN_ONLY_TOOLS

        assert len(ADMIN_ONLY_TOOLS) >= 10

    @pytest.mark.parametrize("tool", ADMIN_ONLY_DB_TOOLS)
    async def test_non_admin_gets_403_on_admin_tool(self, client, app, tool):
        """Non-admin (pro tier) calling an admin-only tool gets 403."""
        key = await _create_agent(app, f"pro-{tool}", tier="pro", balance=5000.0)
        resp = await client.post(
            "/v1/execute",
            json={"tool": tool, "params": {}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403, f"Expected 403 for {tool}, got {resp.status_code}"

    async def test_admin_allowed_on_existing_admin_tool(self, client, app):
        """Admin tier can call admin-only tools like resolve_dispute (not 403)."""
        admin_key = await _create_admin_agent(app, "admin-existing-tool")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "resolve_dispute", "params": {"dispute_id": "fake"}},
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        # May fail for missing dispute, but must NOT be 403
        assert resp.status_code != 403, "Admin should not get 403 for resolve_dispute"


class TestBFLAAdminEndpoints:
    """BFLA audit: process_due_subscriptions and revoke_api_key must be admin-only."""

    def test_process_due_subscriptions_in_admin_only(self):
        """process_due_subscriptions must be in ADMIN_ONLY_TOOLS."""
        from gateway.src.authorization import ADMIN_ONLY_TOOLS

        assert "process_due_subscriptions" in ADMIN_ONLY_TOOLS

    def test_revoke_api_key_in_admin_only(self):
        """revoke_api_key must be in ADMIN_ONLY_TOOLS."""
        from gateway.src.authorization import ADMIN_ONLY_TOOLS

        assert "revoke_api_key" in ADMIN_ONLY_TOOLS

    async def test_pro_key_cannot_process_due_subscriptions(self, client, app):
        """Pro-tier key calling process_due_subscriptions must get 403."""
        key = await _create_agent(app, "pro-bfla-subs", tier="pro", balance=5000.0)
        resp = await client.post(
            "/v1/payments/subscriptions/process-due",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_free_key_cannot_revoke_api_key(self, client, app):
        """Free-tier key calling revoke_api_key must get 403."""
        key = await _create_agent(app, "free-bfla-revoke", tier="free", balance=1000.0)
        resp = await client.post(
            "/v1/execute",
            json={"tool": "revoke_api_key", "params": {"agent_id": "free-bfla-revoke", "key_hash_prefix": "abcd1234"}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_admin_can_process_due_subscriptions(self, client, app):
        """Admin-tier key calling process_due_subscriptions must NOT get 403."""
        admin_key = await _create_admin_agent(app, "admin-bfla-subs")
        resp = await client.post(
            "/v1/payments/subscriptions/process-due",
            headers={"Authorization": f"Bearer {admin_key}"},
        )
        assert resp.status_code != 403
