"""Tests for data lifecycle management (PRD 014).

Covers: hot->warm compression, warm->cold compression, audit log rotation,
vacuum, disk check thresholds.
"""

from __future__ import annotations

import time

import pytest


class TestHotToWarmCompression:
    @pytest.mark.asyncio
    async def test_compress_old_rows_to_daily(self, storage):
        """Rows older than 60 days are aggregated into daily and deleted from raw."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)
        base = time.time() - 90 * 86400  # 90 days ago

        # Insert 10 data points spread over 2 days (>60 days old)
        for i in range(10):
            await storage.store_timeseries(
                agent_id="lifecycle-bot",
                metric_name="sharpe_30d",
                value=float(i + 1),
                timestamp=base + (i % 2) * 86400 + i,
                data_source="self_reported",
            )

        compressed = await manager.compress_hot_to_warm()
        assert compressed > 0

        # Raw rows should be gone
        rows = await storage.query_timeseries(
            "lifecycle-bot", "sharpe_30d", since=base - 86400, limit=100
        )
        old_rows = [r for r in rows if r["timestamp"] < time.time() - 60 * 86400]
        assert len(old_rows) == 0

        # Daily aggregates should exist
        cursor = await storage.db.execute(
            "SELECT * FROM metric_aggregates_daily WHERE agent_id = ?",
            ("lifecycle-bot",),
        )
        daily_rows = await cursor.fetchall()
        assert len(daily_rows) >= 1

    @pytest.mark.asyncio
    async def test_compress_keeps_recent_rows(self, storage):
        """Rows newer than 60 days are NOT compressed."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)
        now = time.time()

        await storage.store_timeseries(
            agent_id="recent-bot",
            metric_name="sharpe_30d",
            value=5.0,
            timestamp=now - 10 * 86400,  # 10 days ago — should stay
            data_source="self_reported",
        )

        await manager.compress_hot_to_warm()

        rows = await storage.query_timeseries("recent-bot", "sharpe_30d")
        assert len(rows) == 1


class TestWarmToColdCompression:
    @pytest.mark.asyncio
    async def test_compress_daily_to_monthly(self, storage):
        """Daily aggregates older than 365 days are compressed to monthly."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)

        # Insert old daily aggregates (>365 days ago)
        for i in range(30):
            day = f"2024-01-{i + 1:02d}"
            await storage.db.execute(
                "INSERT OR REPLACE INTO metric_aggregates_daily "
                "(agent_id, metric_name, day, avg_value, min_value, max_value, sample_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("cold-bot", "sharpe_30d", day, 2.0 + i * 0.1, 1.0, 3.0 + i * 0.1, 10),
            )
        await storage.db.commit()

        compressed = await manager.compress_warm_to_cold()
        assert compressed > 0

        # Monthly aggregate should exist
        cursor = await storage.db.execute(
            "SELECT * FROM metric_aggregates_monthly WHERE agent_id = ? AND month = ?",
            ("cold-bot", "2024-01"),
        )
        monthly = await cursor.fetchone()
        assert monthly is not None
        assert monthly["sample_count"] > 0

        # Old daily rows should be gone
        cursor = await storage.db.execute(
            "SELECT COUNT(*) as cnt FROM metric_aggregates_daily WHERE agent_id = ? AND day LIKE '2024-01%'",
            ("cold-bot",),
        )
        row = await cursor.fetchone()
        assert row["cnt"] == 0


class TestAuditLogRotation:
    @pytest.mark.asyncio
    async def test_rotate_old_nonces(self, storage):
        """Nonces older than 90 days are cleaned up."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)

        # Insert an old nonce (100 days ago)
        old_time = time.time() - 100 * 86400
        await storage.db.execute(
            "INSERT INTO submission_nonces (nonce, agent_id, used_at) VALUES (?, ?, ?)",
            ("old-lifecycle-nonce", "bot-1", old_time),
        )
        # Insert a recent nonce
        await storage.store_nonce("recent-lifecycle-nonce", "bot-1")
        await storage.db.commit()

        deleted = await manager.rotate_audit_logs()
        assert deleted >= 1

        # Old nonce gone
        assert await storage.is_nonce_used("old-lifecycle-nonce") is False
        # Recent nonce still there
        assert await storage.is_nonce_used("recent-lifecycle-nonce") is True


class TestVacuum:
    @pytest.mark.asyncio
    async def test_vacuum_runs_without_error(self, storage):
        """VACUUM completes without raising."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)
        await manager.vacuum()  # Should not raise


class TestDiskUsageCheck:
    @pytest.mark.asyncio
    async def test_disk_check_returns_usage(self, storage):
        """check_disk_usage returns a dict with usage info."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage)
        result = await manager.check_disk_usage()
        assert "db_size_bytes" in result
        assert "warning" in result
        assert isinstance(result["db_size_bytes"], int)

    @pytest.mark.asyncio
    async def test_disk_warning_threshold(self, storage):
        """Warning flag is set correctly based on size threshold."""
        from products.identity.src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(storage, max_db_bytes=1)  # Impossibly small
        result = await manager.check_disk_usage()
        assert result["warning"] is True
