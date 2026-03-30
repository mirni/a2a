"""Data lifecycle management for metric time-series (PRD 014).

Implements tiered retention:
  - Hot (raw metric_timeseries): retained for 60 days
  - Warm (metric_aggregates_daily): retained for 365 days
  - Cold (metric_aggregates_monthly): retained indefinitely

Also handles nonce cleanup and VACUUM operations.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .storage import IdentityStorage


# Default: 60 GB disk limit
_DEFAULT_MAX_DB_BYTES = 60 * 1024 * 1024 * 1024


@dataclass
class DataLifecycleManager:
    """Manages data retention and compression for identity storage."""

    storage: IdentityStorage
    max_db_bytes: int = _DEFAULT_MAX_DB_BYTES

    async def compress_hot_to_warm(self, retention_days: int = 60) -> int:
        """Aggregate raw time-series rows older than *retention_days* into daily
        aggregates, then delete the raw rows.

        Returns the number of raw rows deleted.
        """
        cutoff = time.time() - retention_days * 86400
        db = self.storage.db

        # Find distinct (agent_id, metric_name, day) groups older than cutoff
        cursor = await db.execute(
            "SELECT agent_id, metric_name, "
            "  date(timestamp, 'unixepoch') AS day, "
            "  AVG(value) AS avg_val, "
            "  MIN(value) AS min_val, "
            "  MAX(value) AS max_val, "
            "  COUNT(*) AS cnt "
            "FROM metric_timeseries "
            "WHERE timestamp < ? "
            "GROUP BY agent_id, metric_name, day",
            (cutoff,),
        )
        groups = await cursor.fetchall()

        if not groups:
            return 0

        for g in groups:
            await db.execute(
                "INSERT OR REPLACE INTO metric_aggregates_daily "
                "(agent_id, metric_name, day, avg_value, min_value, max_value, sample_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (g["agent_id"], g["metric_name"], g["day"],
                 g["avg_val"], g["min_val"], g["max_val"], g["cnt"]),
            )

        # Delete compressed raw rows
        delete_cursor = await db.execute(
            "DELETE FROM metric_timeseries WHERE timestamp < ?",
            (cutoff,),
        )
        deleted = delete_cursor.rowcount
        await db.commit()
        return deleted

    async def compress_warm_to_cold(self, retention_days: int = 365) -> int:
        """Aggregate daily rows older than *retention_days* into monthly
        aggregates, then delete the daily rows.

        Returns the number of daily rows deleted.
        """
        cutoff_date = time.strftime(
            "%Y-%m-%d", time.gmtime(time.time() - retention_days * 86400)
        )
        db = self.storage.db

        # Find distinct (agent_id, metric_name, month) groups older than cutoff
        cursor = await db.execute(
            "SELECT agent_id, metric_name, "
            "  substr(day, 1, 7) AS month, "
            "  AVG(avg_value) AS avg_val, "
            "  MIN(min_value) AS min_val, "
            "  MAX(max_value) AS max_val, "
            "  SUM(sample_count) AS cnt "
            "FROM metric_aggregates_daily "
            "WHERE day < ? "
            "GROUP BY agent_id, metric_name, month",
            (cutoff_date,),
        )
        groups = await cursor.fetchall()

        if not groups:
            return 0

        for g in groups:
            await db.execute(
                "INSERT OR REPLACE INTO metric_aggregates_monthly "
                "(agent_id, metric_name, month, avg_value, min_value, max_value, sample_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (g["agent_id"], g["metric_name"], g["month"],
                 g["avg_val"], g["min_val"], g["max_val"], g["cnt"]),
            )

        # Delete compressed daily rows
        delete_cursor = await db.execute(
            "DELETE FROM metric_aggregates_daily WHERE day < ?",
            (cutoff_date,),
        )
        deleted = delete_cursor.rowcount
        await db.commit()
        return deleted

    async def rotate_audit_logs(self, retention_days: int = 90) -> int:
        """Delete old submission nonces beyond retention period.

        Returns the number of nonces deleted.
        """
        cutoff = time.time() - retention_days * 86400
        db = self.storage.db
        cursor = await db.execute(
            "DELETE FROM submission_nonces WHERE used_at < ?",
            (cutoff,),
        )
        await db.commit()
        return cursor.rowcount

    async def vacuum(self) -> None:
        """Run VACUUM to reclaim disk space."""
        await self.storage.db.execute("VACUUM")

    async def check_disk_usage(self) -> dict:
        """Check current database size and return usage info.

        Returns dict with db_size_bytes, warning (bool), and pct_used.
        """
        db_path = self.storage._parse_dsn(self.storage.dsn)
        if db_path == ":memory:":
            return {"db_size_bytes": 0, "warning": False, "pct_used": 0.0}

        try:
            size = os.path.getsize(db_path)
        except OSError:
            size = 0

        pct = (size / self.max_db_bytes * 100) if self.max_db_bytes > 0 else 0.0
        warning = pct >= 80.0

        return {
            "db_size_bytes": size,
            "max_db_bytes": self.max_db_bytes,
            "pct_used": round(pct, 2),
            "warning": warning,
        }
