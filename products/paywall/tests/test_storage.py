"""Tests for PaywallStorage: API keys, rate windows, and audit log."""

from __future__ import annotations

import time

import pytest

from src.storage import PaywallStorage


class TestApiKeyStorage:
    async def test_store_and_lookup_key(self, paywall_storage: PaywallStorage):
        record = await paywall_storage.store_key(
            key_hash="abc123hash",
            agent_id="agent-1",
            tier="pro",
            connector="stripe",
        )
        assert record["key_hash"] == "abc123hash"
        assert record["agent_id"] == "agent-1"
        assert record["tier"] == "pro"
        assert record["connector"] == "stripe"
        assert record["revoked"] == 0

        looked_up = await paywall_storage.lookup_key("abc123hash")
        assert looked_up is not None
        assert looked_up["agent_id"] == "agent-1"
        assert looked_up["tier"] == "pro"

    async def test_lookup_nonexistent_key(self, paywall_storage: PaywallStorage):
        result = await paywall_storage.lookup_key("nonexistent")
        assert result is None

    async def test_revoke_key(self, paywall_storage: PaywallStorage):
        await paywall_storage.store_key("hash1", "agent-1", "free")
        revoked = await paywall_storage.revoke_key("hash1")
        assert revoked is True

        record = await paywall_storage.lookup_key("hash1")
        assert record is not None
        assert record["revoked"] == 1

    async def test_revoke_nonexistent_key(self, paywall_storage: PaywallStorage):
        revoked = await paywall_storage.revoke_key("nonexistent")
        assert revoked is False

    async def test_revoke_already_revoked(self, paywall_storage: PaywallStorage):
        await paywall_storage.store_key("hash1", "agent-1", "free")
        await paywall_storage.revoke_key("hash1")
        # Second revoke should return False (already revoked)
        revoked = await paywall_storage.revoke_key("hash1")
        assert revoked is False

    async def test_get_keys_for_agent(self, paywall_storage: PaywallStorage):
        await paywall_storage.store_key("hash1", "agent-1", "free")
        await paywall_storage.store_key("hash2", "agent-1", "pro")
        await paywall_storage.store_key("hash3", "agent-2", "free")

        keys = await paywall_storage.get_keys_for_agent("agent-1")
        assert len(keys) == 2
        assert all(k["agent_id"] == "agent-1" for k in keys)

    async def test_get_keys_for_unknown_agent(self, paywall_storage: PaywallStorage):
        keys = await paywall_storage.get_keys_for_agent("unknown")
        assert keys == []


class TestRateWindows:
    async def test_get_rate_count_empty(self, paywall_storage: PaywallStorage):
        count = await paywall_storage.get_rate_count("agent-1", "hourly", time.time() - 3600)
        assert count == 0

    async def test_increment_creates_window(self, paywall_storage: PaywallStorage):
        now = time.time()
        window_start = now - 3600
        count = await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        assert count == 1

    async def test_increment_accumulates(self, paywall_storage: PaywallStorage):
        now = time.time()
        window_start = now - 3600
        await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        count = await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        assert count == 3

    async def test_window_reset_on_expire(self, paywall_storage: PaywallStorage):
        old_start = time.time() - 7200  # 2 hours ago
        await paywall_storage.increment_rate_count("agent-1", "hourly", old_start)
        await paywall_storage.increment_rate_count("agent-1", "hourly", old_start)

        # New window (more recent start)
        new_start = time.time() - 3600
        count = await paywall_storage.get_rate_count("agent-1", "hourly", new_start)
        assert count == 0  # Old window expired

    async def test_separate_agents(self, paywall_storage: PaywallStorage):
        window_start = time.time() - 3600
        await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        await paywall_storage.increment_rate_count("agent-1", "hourly", window_start)
        await paywall_storage.increment_rate_count("agent-2", "hourly", window_start)

        count1 = await paywall_storage.get_rate_count("agent-1", "hourly", window_start)
        count2 = await paywall_storage.get_rate_count("agent-2", "hourly", window_start)
        assert count1 == 2
        assert count2 == 1


class TestAuditLog:
    async def test_record_and_retrieve_audit(self, paywall_storage: PaywallStorage):
        row_id = await paywall_storage.record_audit(
            agent_id="agent-1",
            connector="stripe",
            function="create_payment",
            tier="pro",
            cost=1.0,
            allowed=True,
        )
        assert row_id > 0

        logs = await paywall_storage.get_audit_log("agent-1")
        assert len(logs) == 1
        assert logs[0]["connector"] == "stripe"
        assert logs[0]["function"] == "create_payment"
        assert logs[0]["allowed"] == 1

    async def test_audit_denied_entry(self, paywall_storage: PaywallStorage):
        await paywall_storage.record_audit(
            agent_id="agent-1",
            connector="stripe",
            function="create_payment",
            tier="free",
            cost=1.0,
            allowed=False,
            reason="Rate limit exceeded",
        )

        logs = await paywall_storage.get_audit_log("agent-1")
        assert len(logs) == 1
        assert logs[0]["allowed"] == 0
        assert logs[0]["reason"] == "Rate limit exceeded"

    async def test_audit_log_since_filter(self, paywall_storage: PaywallStorage):
        # Record two entries
        await paywall_storage.record_audit(agent_id="agent-1", function="fn1")
        now = time.time()
        await paywall_storage.record_audit(agent_id="agent-1", function="fn2")

        # Filter should only return fn2
        logs = await paywall_storage.get_audit_log("agent-1", since=now - 0.01)
        assert len(logs) >= 1
        functions = [l["function"] for l in logs]
        assert "fn2" in functions

    async def test_purge_audit_log(self, paywall_storage: PaywallStorage):
        await paywall_storage.record_audit(agent_id="agent-1", function="old")
        now = time.time()

        deleted = await paywall_storage.purge_audit_log(before=now + 1)
        assert deleted == 1

        logs = await paywall_storage.get_audit_log("agent-1")
        assert len(logs) == 0

    async def test_audit_limit(self, paywall_storage: PaywallStorage):
        for i in range(5):
            await paywall_storage.record_audit(agent_id="agent-1", function=f"fn{i}")

        logs = await paywall_storage.get_audit_log("agent-1", limit=3)
        assert len(logs) == 3


class TestStorageLifecycle:
    async def test_not_connected_raises(self):
        storage = PaywallStorage(dsn="sqlite:///unused.db")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = storage.db
