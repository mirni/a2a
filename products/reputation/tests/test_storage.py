"""Tests for reputation pipeline storage layer."""

from __future__ import annotations

import time

import pytest
import pytest_asyncio

from products.reputation.src.models import ProbeTarget
from products.reputation.src.storage import ReputationStorage


class TestReputationStorageConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_tables(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        storage = ReputationStorage(dsn=f"sqlite:///{db_path}")
        await storage.connect()
        cursor = await storage.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='probe_targets'"
        )
        row = await cursor.fetchone()
        assert row is not None
        await storage.close()

    @pytest.mark.asyncio
    async def test_connect_creates_index(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        storage = ReputationStorage(dsn=f"sqlite:///{db_path}")
        await storage.connect()
        cursor = await storage.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_target_active'"
        )
        row = await cursor.fetchone()
        assert row is not None
        await storage.close()

    @pytest.mark.asyncio
    async def test_db_property_raises_before_connect(self):
        storage = ReputationStorage(dsn="sqlite:///test.db")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = storage.db

    @pytest.mark.asyncio
    async def test_close_without_connect(self):
        storage = ReputationStorage(dsn="sqlite:///test.db")
        await storage.close()

    @pytest.mark.asyncio
    async def test_double_connect(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        storage = ReputationStorage(dsn=f"sqlite:///{db_path}")
        await storage.connect()
        await storage.connect()
        await storage.close()


class TestAddTarget:
    @pytest.mark.asyncio
    async def test_add_target(self, reputation_storage):
        target = ProbeTarget(server_id="svc-1", url="https://example.com")
        result = await reputation_storage.add_target(target)
        assert result.server_id == "svc-1"

    @pytest.mark.asyncio
    async def test_add_target_custom_intervals(self, reputation_storage):
        target = ProbeTarget(
            server_id="svc-2",
            url="https://example.com",
            probe_interval=60.0,
            scan_interval=600.0,
        )
        await reputation_storage.add_target(target)
        retrieved = await reputation_storage.get_target("svc-2")
        assert retrieved is not None
        assert retrieved.probe_interval == 60.0
        assert retrieved.scan_interval == 600.0

    @pytest.mark.asyncio
    async def test_add_target_replaces_existing(self, reputation_storage):
        t1 = ProbeTarget(server_id="svc-1", url="https://old.com")
        await reputation_storage.add_target(t1)
        t2 = ProbeTarget(server_id="svc-1", url="https://new.com")
        await reputation_storage.add_target(t2)
        result = await reputation_storage.get_target("svc-1")
        assert result.url == "https://new.com"

    @pytest.mark.asyncio
    async def test_add_multiple_targets(self, reputation_storage):
        for i in range(5):
            await reputation_storage.add_target(
                ProbeTarget(server_id=f"svc-{i}", url=f"https://svc{i}.com")
            )
        targets = await reputation_storage.list_targets(active_only=False)
        assert len(targets) == 5


class TestRemoveTarget:
    @pytest.mark.asyncio
    async def test_remove_existing(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        removed = await reputation_storage.remove_target("svc-1")
        assert removed is True
        assert await reputation_storage.get_target("svc-1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, reputation_storage):
        removed = await reputation_storage.remove_target("nonexistent")
        assert removed is False


class TestDeactivateActivate:
    @pytest.mark.asyncio
    async def test_deactivate_target(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        result = await reputation_storage.deactivate_target("svc-1")
        assert result is True
        target = await reputation_storage.get_target("svc-1")
        assert target.active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent(self, reputation_storage):
        result = await reputation_storage.deactivate_target("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_activate_target(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", active=False)
        )
        result = await reputation_storage.activate_target("svc-1")
        assert result is True
        target = await reputation_storage.get_target("svc-1")
        assert target.active is True

    @pytest.mark.asyncio
    async def test_activate_nonexistent(self, reputation_storage):
        result = await reputation_storage.activate_target("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_deactivated_not_in_active_list(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-2", url="https://example2.com")
        )
        await reputation_storage.deactivate_target("svc-1")
        active = await reputation_storage.list_targets(active_only=True)
        assert len(active) == 1
        assert active[0].server_id == "svc-2"

    @pytest.mark.asyncio
    async def test_deactivated_in_full_list(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        await reputation_storage.deactivate_target("svc-1")
        all_targets = await reputation_storage.list_targets(active_only=False)
        assert len(all_targets) == 1


class TestGetTarget:
    @pytest.mark.asyncio
    async def test_get_existing(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        target = await reputation_storage.get_target("svc-1")
        assert target is not None
        assert target.server_id == "svc-1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, reputation_storage):
        target = await reputation_storage.get_target("nonexistent")
        assert target is None


class TestListTargets:
    @pytest.mark.asyncio
    async def test_list_empty(self, reputation_storage):
        targets = await reputation_storage.list_targets()
        assert targets == []

    @pytest.mark.asyncio
    async def test_list_active_only(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://a.com", active=True)
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-2", url="https://b.com", active=False)
        )
        active = await reputation_storage.list_targets(active_only=True)
        assert len(active) == 1
        assert active[0].server_id == "svc-1"

    @pytest.mark.asyncio
    async def test_list_all(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://a.com", active=True)
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-2", url="https://b.com", active=False)
        )
        all_targets = await reputation_storage.list_targets(active_only=False)
        assert len(all_targets) == 2

    @pytest.mark.asyncio
    async def test_list_ordered_by_server_id(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-c", url="https://c.com")
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-a", url="https://a.com")
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-b", url="https://b.com")
        )
        targets = await reputation_storage.list_targets()
        ids = [t.server_id for t in targets]
        assert ids == ["svc-a", "svc-b", "svc-c"]


class TestDueForProbe:
    @pytest.mark.asyncio
    async def test_never_probed_is_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", probe_interval=300.0)
        )
        due = await reputation_storage.get_due_for_probe(now=1000.0)
        assert len(due) == 1

    @pytest.mark.asyncio
    async def test_recently_probed_not_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", probe_interval=300.0)
        )
        await reputation_storage.update_last_probed("svc-1", 900.0)
        due = await reputation_storage.get_due_for_probe(now=1000.0)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_old_probe_is_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", probe_interval=300.0)
        )
        await reputation_storage.update_last_probed("svc-1", 600.0)
        due = await reputation_storage.get_due_for_probe(now=1000.0)
        assert len(due) == 1

    @pytest.mark.asyncio
    async def test_inactive_not_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", active=False)
        )
        due = await reputation_storage.get_due_for_probe(now=1000.0)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_exact_interval_boundary(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", probe_interval=300.0)
        )
        await reputation_storage.update_last_probed("svc-1", 700.0)
        due = await reputation_storage.get_due_for_probe(now=1000.0)
        assert len(due) == 1


class TestDueForScan:
    @pytest.mark.asyncio
    async def test_never_scanned_is_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", scan_interval=3600.0)
        )
        due = await reputation_storage.get_due_for_scan(now=1000.0)
        assert len(due) == 1

    @pytest.mark.asyncio
    async def test_recently_scanned_not_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", scan_interval=3600.0)
        )
        await reputation_storage.update_last_scanned("svc-1", 900.0)
        due = await reputation_storage.get_due_for_scan(now=1000.0)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_old_scan_is_due(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com", scan_interval=3600.0)
        )
        await reputation_storage.update_last_scanned("svc-1", 100.0)
        due = await reputation_storage.get_due_for_scan(now=5000.0)
        assert len(due) == 1


class TestUpdateTimestamps:
    @pytest.mark.asyncio
    async def test_update_last_probed(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        await reputation_storage.update_last_probed("svc-1", 12345.0)
        target = await reputation_storage.get_target("svc-1")
        assert target.last_probed == 12345.0

    @pytest.mark.asyncio
    async def test_update_last_scanned(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        await reputation_storage.update_last_scanned("svc-1", 67890.0)
        target = await reputation_storage.get_target("svc-1")
        assert target.last_scanned == 67890.0


class TestUpdateIntervals:
    @pytest.mark.asyncio
    async def test_update_probe_interval(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        result = await reputation_storage.update_intervals("svc-1", probe_interval=120.0)
        assert result is True
        target = await reputation_storage.get_target("svc-1")
        assert target.probe_interval == 120.0

    @pytest.mark.asyncio
    async def test_update_scan_interval(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        result = await reputation_storage.update_intervals("svc-1", scan_interval=7200.0)
        assert result is True
        target = await reputation_storage.get_target("svc-1")
        assert target.scan_interval == 7200.0

    @pytest.mark.asyncio
    async def test_update_both_intervals(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://example.com")
        )
        result = await reputation_storage.update_intervals(
            "svc-1", probe_interval=60.0, scan_interval=1800.0
        )
        assert result is True
        target = await reputation_storage.get_target("svc-1")
        assert target.probe_interval == 60.0
        assert target.scan_interval == 1800.0

    @pytest.mark.asyncio
    async def test_update_no_intervals(self, reputation_storage):
        result = await reputation_storage.update_intervals("svc-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, reputation_storage):
        result = await reputation_storage.update_intervals("nonexistent", probe_interval=60.0)
        assert result is False


class TestCountTargets:
    @pytest.mark.asyncio
    async def test_count_empty(self, reputation_storage):
        count = await reputation_storage.count_targets()
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_active(self, reputation_storage):
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-1", url="https://a.com", active=True)
        )
        await reputation_storage.add_target(
            ProbeTarget(server_id="svc-2", url="https://b.com", active=False)
        )
        assert await reputation_storage.count_targets(active_only=True) == 1
        assert await reputation_storage.count_targets(active_only=False) == 2
