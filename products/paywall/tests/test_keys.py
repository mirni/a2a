"""Tests for API key management."""

from __future__ import annotations

import time

import pytest
from src.keys import InvalidKeyError, KeyManager, _hash_key


class TestKeyGeneration:
    async def test_create_key_format(self, key_manager: KeyManager):
        result = await key_manager.create_key(agent_id="agent-1", tier="free")
        key = result["key"]
        assert key.startswith("a2a_free_")
        assert len(key) == len("a2a_free_") + 24  # 12 bytes = 24 hex chars

    async def test_create_pro_key(self, key_manager: KeyManager):
        result = await key_manager.create_key(agent_id="agent-1", tier="pro")
        assert result["key"].startswith("a2a_pro_")
        assert result["tier"] == "pro"
        assert result["agent_id"] == "agent-1"

    async def test_create_enterprise_key(self, key_manager: KeyManager):
        result = await key_manager.create_key(agent_id="agent-1", tier="enterprise")
        assert result["key"].startswith("a2a_enterprise_")
        assert result["tier"] == "enterprise"

    async def test_create_key_with_connector(self, key_manager: KeyManager):
        result = await key_manager.create_key(agent_id="agent-1", tier="pro", connector="stripe")
        assert result["connector"] == "stripe"

    async def test_invalid_tier_rejected(self, key_manager: KeyManager):
        with pytest.raises(ValueError, match="Unknown tier"):
            await key_manager.create_key(agent_id="agent-1", tier="platinum")

    async def test_key_hash_stored(self, key_manager: KeyManager):
        result = await key_manager.create_key(agent_id="agent-1", tier="free")
        assert result["key_hash"] == _hash_key(result["key"])


class TestKeyValidation:
    async def test_validate_valid_key(self, key_manager: KeyManager):
        created = await key_manager.create_key(agent_id="agent-1", tier="pro")
        record = await key_manager.validate_key(created["key"])
        assert record["agent_id"] == "agent-1"
        assert record["tier"] == "pro"

    async def test_validate_invalid_format(self, key_manager: KeyManager):
        with pytest.raises(InvalidKeyError, match="Invalid key format"):
            await key_manager.validate_key("not_a_valid_key")

    async def test_validate_empty_key(self, key_manager: KeyManager):
        with pytest.raises(InvalidKeyError, match="Invalid key format"):
            await key_manager.validate_key("")

    async def test_validate_nonexistent_key(self, key_manager: KeyManager):
        with pytest.raises(InvalidKeyError, match="not found"):
            await key_manager.validate_key("a2a_pro_0000000000000000000000ff")

    async def test_validate_revoked_key(self, key_manager: KeyManager):
        """v1.2.2 audit HIGH-7: revoked keys honor a 300s grace window,
        so the only way to check the hard-revoke path is to backdate
        ``revoked_at`` past the grace window.
        """
        from src.keys import KEY_ROTATION_GRACE_SECONDS

        created = await key_manager.create_key(agent_id="agent-1", tier="pro")
        await key_manager.revoke_key(created["key"])
        # Backdate revoked_at so the grace window has already elapsed.
        past = time.time() - (KEY_ROTATION_GRACE_SECONDS + 1)
        await key_manager.storage.db.execute("UPDATE api_keys SET revoked_at = ? WHERE revoked = 1", (past,))
        await key_manager.storage.db.commit()

        with pytest.raises(InvalidKeyError, match="revoked"):
            await key_manager.validate_key(created["key"])

    async def test_validate_revoked_key_in_grace_window(self, key_manager: KeyManager):
        """v1.2.2 audit HIGH-7: freshly-revoked keys continue to
        authenticate during the grace window so rotation is safe.
        """
        created = await key_manager.create_key(agent_id="agent-1", tier="pro")
        await key_manager.revoke_key(created["key"])

        record = await key_manager.validate_key(created["key"])
        assert record["agent_id"] == "agent-1"
        assert "_key_grace_seconds_remaining" in record


class TestKeyRevocation:
    async def test_revoke_existing_key(self, key_manager: KeyManager):
        created = await key_manager.create_key(agent_id="agent-1", tier="pro")
        result = await key_manager.revoke_key(created["key"])
        assert result is True

    async def test_revoke_nonexistent_key(self, key_manager: KeyManager):
        result = await key_manager.revoke_key("a2a_pro_0000000000000000000000ff")
        assert result is False


class TestKeyLookup:
    async def test_lookup_agent(self, key_manager: KeyManager):
        created = await key_manager.create_key(agent_id="agent-42", tier="enterprise")
        agent_id, tier = await key_manager.lookup_agent(created["key"])
        assert agent_id == "agent-42"
        assert tier == "enterprise"

    async def test_get_agent_keys(self, key_manager: KeyManager):
        await key_manager.create_key(agent_id="agent-1", tier="free")
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        keys = await key_manager.get_agent_keys("agent-1")
        assert len(keys) == 2

    async def test_get_agent_keys_empty(self, key_manager: KeyManager):
        keys = await key_manager.get_agent_keys("unknown-agent")
        assert keys == []

    async def test_multiple_agents_isolated(self, key_manager: KeyManager):
        await key_manager.create_key(agent_id="agent-1", tier="free")
        await key_manager.create_key(agent_id="agent-2", tier="pro")

        keys1 = await key_manager.get_agent_keys("agent-1")
        keys2 = await key_manager.get_agent_keys("agent-2")
        assert len(keys1) == 1
        assert len(keys2) == 1
        assert keys1[0]["tier"] == "free"
        assert keys2[0]["tier"] == "pro"


class TestOnKeyCreatedCallback:
    """v1.2.2 audit HIGH-8: KeyManager fires on_key_created after store."""

    async def test_callback_invoked_with_agent_id(self, key_manager: KeyManager):
        """The hook should receive the agent_id of the newly-issued key."""
        received: list[str] = []

        async def hook(agent_id: str) -> None:
            received.append(agent_id)

        key_manager.on_key_created = hook
        await key_manager.create_key(agent_id="bot-hook-ok", tier="pro")
        assert received == ["bot-hook-ok"]

    async def test_callback_failure_does_not_block_key_issuance(self, key_manager: KeyManager, caplog):
        """A raised exception inside the hook must be logged and swallowed
        so the key is still returned to the caller. A downstream identity
        outage cannot block new provisioning.
        """
        import logging

        async def broken_hook(agent_id: str) -> None:
            raise RuntimeError("identity-down")

        key_manager.on_key_created = broken_hook

        with caplog.at_level(logging.WARNING, logger="paywall.keys"):
            result = await key_manager.create_key(agent_id="bot-hook-fail", tier="pro")

        assert result["key"].startswith("a2a_pro_")
        assert result["agent_id"] == "bot-hook-fail"
        assert any("on_key_created" in r.message for r in caplog.records)
