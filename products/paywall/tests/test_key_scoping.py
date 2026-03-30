"""Tests for API key scoping and permissions (Item 7).

Covers:
- allowed_tools restriction
- allowed_agent_ids restriction
- scope-based access control (read/write/admin)
- key expiration
- backward compatibility (unscoped keys)
- create_key with scopes persists correctly
- validate_key returns scope info
- negative: empty scopes raises error
"""

from __future__ import annotations

import time

import pytest
from src.keys import ExpiredKeyError, InvalidKeyError, KeyManager, KeyScopeError
from src.scoping import ScopeChecker, ToolScope


# ---------------------------------------------------------------------------
# ToolScope classification
# ---------------------------------------------------------------------------


class TestToolScope:
    """Test the tool scope classification."""

    def test_read_tools(self):
        assert ToolScope.for_tool("get_balance") == "read"
        assert ToolScope.for_tool("get_events") == "read"
        assert ToolScope.for_tool("search_services") == "read"
        assert ToolScope.for_tool("get_usage_summary") == "read"
        assert ToolScope.for_tool("get_transactions") == "read"
        assert ToolScope.for_tool("get_trust_score") == "read"
        assert ToolScope.for_tool("list_webhooks") == "read"
        assert ToolScope.for_tool("get_messages") == "read"

    def test_write_tools(self):
        assert ToolScope.for_tool("create_intent") == "write"
        assert ToolScope.for_tool("deposit") == "write"
        assert ToolScope.for_tool("send_message") == "write"
        assert ToolScope.for_tool("create_escrow") == "write"
        assert ToolScope.for_tool("register_service") == "write"
        assert ToolScope.for_tool("register_webhook") == "write"
        assert ToolScope.for_tool("create_wallet") == "write"
        assert ToolScope.for_tool("withdraw") == "write"

    def test_admin_tools(self):
        assert ToolScope.for_tool("backup_database") == "admin"
        assert ToolScope.for_tool("restore_database") == "admin"
        assert ToolScope.for_tool("check_db_integrity") == "admin"
        assert ToolScope.for_tool("list_backups") == "admin"

    def test_unknown_tool_defaults_to_write(self):
        assert ToolScope.for_tool("unknown_future_tool") == "write"


# ---------------------------------------------------------------------------
# ScopeChecker (pure logic)
# ---------------------------------------------------------------------------


class TestScopeChecker:
    """Test pure scope-checking logic."""

    def test_read_scope_allows_read_tools(self):
        checker = ScopeChecker(scopes=["read"])
        checker.check_scope("get_balance")  # should not raise

    def test_read_scope_blocks_write_tools(self):
        checker = ScopeChecker(scopes=["read"])
        with pytest.raises(KeyScopeError, match="write"):
            checker.check_scope("create_intent")

    def test_read_scope_blocks_admin_tools(self):
        checker = ScopeChecker(scopes=["read"])
        with pytest.raises(KeyScopeError, match="admin"):
            checker.check_scope("backup_database")

    def test_write_scope_allows_read_and_write(self):
        checker = ScopeChecker(scopes=["read", "write"])
        checker.check_scope("get_balance")  # read
        checker.check_scope("create_intent")  # write

    def test_write_scope_blocks_admin(self):
        checker = ScopeChecker(scopes=["read", "write"])
        with pytest.raises(KeyScopeError, match="admin"):
            checker.check_scope("backup_database")

    def test_admin_scope_allows_everything(self):
        checker = ScopeChecker(scopes=["read", "write", "admin"])
        checker.check_scope("get_balance")
        checker.check_scope("create_intent")
        checker.check_scope("backup_database")

    def test_allowed_tools_restricts(self):
        checker = ScopeChecker(scopes=["read", "write"], allowed_tools=["get_balance", "deposit"])
        checker.check_tool("get_balance")  # allowed
        with pytest.raises(KeyScopeError, match="not in allowed tools"):
            checker.check_tool("create_intent")

    def test_allowed_tools_none_means_all(self):
        checker = ScopeChecker(scopes=["read", "write"], allowed_tools=None)
        checker.check_tool("get_balance")
        checker.check_tool("create_intent")

    def test_allowed_agent_ids_restricts(self):
        checker = ScopeChecker(scopes=["read", "write"], allowed_agent_ids=["agent-1", "agent-2"])
        checker.check_agent_id("agent-1")  # allowed
        with pytest.raises(KeyScopeError, match="not in allowed agent_ids"):
            checker.check_agent_id("agent-99")

    def test_allowed_agent_ids_none_means_all(self):
        checker = ScopeChecker(scopes=["read", "write"], allowed_agent_ids=None)
        checker.check_agent_id("any-agent")  # should not raise


# ---------------------------------------------------------------------------
# KeyManager.create_key with scoping
# ---------------------------------------------------------------------------


class TestCreateKeyWithScopes:
    """Test that create_key stores scope parameters."""

    async def test_create_key_default_scopes(self, key_manager: KeyManager):
        """Keys without explicit scopes get default ['read', 'write']."""
        result = await key_manager.create_key(agent_id="agent-1", tier="free")
        assert result["scopes"] == ["read", "write"]
        assert result["allowed_tools"] is None
        assert result["allowed_agent_ids"] is None
        assert result["expires_at"] is None

    async def test_create_key_custom_scopes(self, key_manager: KeyManager):
        result = await key_manager.create_key(
            agent_id="agent-1",
            tier="pro",
            scopes=["read"],
            allowed_tools=["get_balance", "get_events"],
            allowed_agent_ids=["agent-1"],
            expires_at=time.time() + 3600,
        )
        assert result["scopes"] == ["read"]
        assert result["allowed_tools"] == ["get_balance", "get_events"]
        assert result["allowed_agent_ids"] == ["agent-1"]
        assert result["expires_at"] is not None

    async def test_create_key_admin_scope(self, key_manager: KeyManager):
        result = await key_manager.create_key(
            agent_id="admin-agent",
            tier="enterprise",
            scopes=["read", "write", "admin"],
        )
        assert "admin" in result["scopes"]

    async def test_create_key_empty_scopes_raises(self, key_manager: KeyManager):
        """Creating a key with empty scopes list is invalid."""
        with pytest.raises(ValueError, match="at least one scope"):
            await key_manager.create_key(
                agent_id="agent-1",
                tier="free",
                scopes=[],
            )

    async def test_create_key_invalid_scope_raises(self, key_manager: KeyManager):
        """Creating a key with an unknown scope is invalid."""
        with pytest.raises(ValueError, match="Invalid scope"):
            await key_manager.create_key(
                agent_id="agent-1",
                tier="free",
                scopes=["read", "superadmin"],
            )


# ---------------------------------------------------------------------------
# KeyManager.validate_key returns scope info
# ---------------------------------------------------------------------------


class TestValidateKeyReturnsScopes:
    """Test that validate_key returns scope info in the record."""

    async def test_validate_returns_scopes(self, key_manager: KeyManager):
        created = await key_manager.create_key(
            agent_id="agent-1",
            tier="free",
            scopes=["read"],
            allowed_tools=["get_balance"],
            allowed_agent_ids=["agent-1"],
        )
        record = await key_manager.validate_key(created["key"])
        assert record["scopes"] == ["read"]
        assert record["allowed_tools"] == ["get_balance"]
        assert record["allowed_agent_ids"] == ["agent-1"]

    async def test_validate_returns_default_scopes(self, key_manager: KeyManager):
        created = await key_manager.create_key(agent_id="agent-1", tier="free")
        record = await key_manager.validate_key(created["key"])
        assert record["scopes"] == ["read", "write"]
        assert record["allowed_tools"] is None
        assert record["allowed_agent_ids"] is None


# ---------------------------------------------------------------------------
# Expired key returns appropriate error
# ---------------------------------------------------------------------------


class TestKeyExpiration:
    """Test that expired keys are rejected."""

    async def test_expired_key_rejected(self, key_manager: KeyManager):
        """A key with expires_at in the past should be rejected."""
        created = await key_manager.create_key(
            agent_id="agent-1",
            tier="free",
            expires_at=time.time() - 60,  # expired 60 seconds ago
        )
        with pytest.raises(ExpiredKeyError, match="expired"):
            await key_manager.validate_key(created["key"])

    async def test_non_expired_key_accepted(self, key_manager: KeyManager):
        """A key with expires_at in the future should work."""
        created = await key_manager.create_key(
            agent_id="agent-1",
            tier="free",
            expires_at=time.time() + 3600,
        )
        record = await key_manager.validate_key(created["key"])
        assert record["agent_id"] == "agent-1"

    async def test_no_expiration_never_expires(self, key_manager: KeyManager):
        """A key with no expires_at never expires."""
        created = await key_manager.create_key(agent_id="agent-1", tier="free")
        record = await key_manager.validate_key(created["key"])
        assert record["expires_at"] is None
        assert record["agent_id"] == "agent-1"


# ---------------------------------------------------------------------------
# Backward compatibility (keys without scoping work as before)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing keys without scoping still work."""

    async def test_old_key_still_validates(self, key_manager: KeyManager):
        """Keys created without scoping work and have sensible defaults."""
        created = await key_manager.create_key(agent_id="legacy-agent", tier="free")
        record = await key_manager.validate_key(created["key"])
        assert record["agent_id"] == "legacy-agent"
        assert record["tier"] == "free"
        # defaults
        assert record["scopes"] == ["read", "write"]
        assert record["allowed_tools"] is None
        assert record["allowed_agent_ids"] is None
        assert record["expires_at"] is None

    async def test_old_key_lookup_agent_unchanged(self, key_manager: KeyManager):
        """lookup_agent still returns (agent_id, tier) without error."""
        created = await key_manager.create_key(agent_id="legacy-agent", tier="pro")
        agent_id, tier = await key_manager.lookup_agent(created["key"])
        assert agent_id == "legacy-agent"
        assert tier == "pro"
