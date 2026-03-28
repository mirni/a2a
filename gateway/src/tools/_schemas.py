"""Centralized schema creation for tool-managed tables.

Called once during lifespan startup to avoid repeated CREATE TABLE IF NOT EXISTS
in every tool function call.
"""

from __future__ import annotations

import aiosqlite


async def ensure_budget_caps_table(db: aiosqlite.Connection) -> None:
    """Create the budget_caps table if it doesn't exist."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS budget_caps (
            agent_id TEXT PRIMARY KEY,
            daily_cap REAL,
            monthly_cap REAL,
            alert_threshold REAL NOT NULL DEFAULT 0.8
        )"""
    )
    await db.commit()


async def ensure_service_ratings_table(db: aiosqlite.Connection) -> None:
    """Create the service_ratings table if it doesn't exist."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS service_ratings (
            service_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (service_id, agent_id)
        )"""
    )
    await db.commit()


async def ensure_event_schemas_table(db: aiosqlite.Connection) -> None:
    """Create the event_schemas table if it doesn't exist."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS event_schemas (
            event_type TEXT PRIMARY KEY,
            schema     TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )"""
    )
    await db.commit()
