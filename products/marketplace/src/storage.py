"""SQLite storage backend for the marketplace."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite


class MarketplaceStorage:
    """Async SQLite storage for marketplace data."""

    def __init__(self, dsn: str = "sqlite:///:memory:") -> None:
        self._dsn = dsn
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Storage not connected. Call await storage.connect() first.")
        return self._db

    def _db_path(self) -> str:
        return self._dsn.replace("sqlite:///", "")

    # Register ``(table, column, col_type)`` triples here when a column is
    # added to an existing table. Entries are applied BEFORE _create_tables()
    # runs its DDL, so any new CREATE INDEX referencing the column won't
    # abort on pre-existing DBs. See audit finding C2 and
    # ``shared_src.storage_migrations``.
    _COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = ()

    async def connect(self) -> None:
        try:
            from shared_src.db_security import harden_connection
            from shared_src.storage_migrations import apply_column_migrations
        except ImportError:
            from src.db_security import harden_connection
            from src.storage_migrations import apply_column_migrations

        path = self._db_path()
        if path == ":memory:":
            self._db = await aiosqlite.connect(":memory:")
        else:
            self._db = await aiosqlite.connect(path)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)
        await apply_column_migrations(self._db, self._COLUMN_MIGRATIONS)
        await self._create_tables()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _create_tables(self) -> None:
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                category TEXT NOT NULL,
                pricing_json TEXT NOT NULL DEFAULT '{}',
                sla_json TEXT NOT NULL DEFAULT '{}',
                endpoint TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                org_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS service_tools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL REFERENCES services(id) ON DELETE CASCADE,
                tool_name TEXT NOT NULL,
                UNIQUE(service_id, tool_name)
            );

            CREATE TABLE IF NOT EXISTS service_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL REFERENCES services(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                UNIQUE(service_id, tag)
            );

            CREATE INDEX IF NOT EXISTS idx_services_provider ON services(provider_id);
            CREATE INDEX IF NOT EXISTS idx_services_category ON services(category);
            CREATE INDEX IF NOT EXISTS idx_services_status ON services(status);
            CREATE INDEX IF NOT EXISTS idx_service_tags_tag ON service_tags(tag);
            CREATE INDEX IF NOT EXISTS idx_service_tools_name ON service_tools(tool_name);

            CREATE TABLE IF NOT EXISTS service_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                review TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                UNIQUE(service_id, agent_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ratings_service ON service_ratings(service_id);
            CREATE INDEX IF NOT EXISTS idx_ratings_agent ON service_ratings(agent_id);

            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                message TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_suggestions_category ON suggestions(category);
            CREATE INDEX IF NOT EXISTS idx_suggestions_created ON suggestions(created_at);
        """)

    def _generate_id(self) -> str:
        return f"svc-{uuid.uuid4().hex[:12]}"

    async def insert_service(
        self,
        provider_id: str,
        name: str,
        description: str,
        category: str,
        tools: list[str],
        pricing: dict[str, Any],
        sla: dict[str, Any],
        tags: list[str],
        endpoint: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Insert a new service and return its ID."""
        service_id = self._generate_id()
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            """INSERT INTO services (id, provider_id, name, description, category,
               pricing_json, sla_json, endpoint, status, metadata_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
            (
                service_id,
                provider_id,
                name,
                description,
                category,
                json.dumps(pricing),
                json.dumps(sla),
                endpoint,
                json.dumps(metadata or {}),
                now,
                now,
            ),
        )
        for tool in tools:
            await self.db.execute(
                "INSERT INTO service_tools (service_id, tool_name) VALUES (?, ?)",
                (service_id, tool),
            )
        for tag in tags:
            await self.db.execute(
                "INSERT INTO service_tags (service_id, tag) VALUES (?, ?)",
                (service_id, tag),
            )
        await self.db.commit()
        return service_id

    async def get_service(self, service_id: str) -> dict[str, Any] | None:
        """Get a service by ID with its tools and tags."""
        cursor = await self.db.execute("SELECT * FROM services WHERE id = ?", (service_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return await self._enrich_service(dict(row))

    async def get_services_by_provider(self, provider_id: str) -> list[dict[str, Any]]:
        """Get all services for a provider."""
        cursor = await self.db.execute(
            "SELECT * FROM services WHERE provider_id = ? ORDER BY created_at DESC",
            (provider_id,),
        )
        rows = await cursor.fetchall()
        return [await self._enrich_service(dict(r)) for r in rows]

    async def update_service(
        self,
        service_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        pricing: dict[str, Any] | None = None,
        sla: dict[str, Any] | None = None,
        endpoint: str | None = None,
        status: str | None = None,
        tools: list[str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Update a service. Returns True if found and updated."""
        existing = await self.get_service(service_id)
        if existing is None:
            return False

        updates: list[str] = []
        values: list[Any] = []
        now = datetime.now(UTC).isoformat()

        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if description is not None:
            updates.append("description = ?")
            values.append(description)
        if category is not None:
            updates.append("category = ?")
            values.append(category)
        if pricing is not None:
            updates.append("pricing_json = ?")
            values.append(json.dumps(pricing))
        if sla is not None:
            updates.append("sla_json = ?")
            values.append(json.dumps(sla))
        if endpoint is not None:
            updates.append("endpoint = ?")
            values.append(endpoint)
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if metadata is not None:
            updates.append("metadata_json = ?")
            values.append(json.dumps(metadata))

        updates.append("updated_at = ?")
        values.append(now)
        values.append(service_id)

        await self.db.execute(  # nosemgrep: sqlalchemy-execute-raw-query
            f"UPDATE services SET {', '.join(updates)} WHERE id = ?",
            values,
        )

        if tools is not None:
            await self.db.execute("DELETE FROM service_tools WHERE service_id = ?", (service_id,))
            for tool in tools:
                await self.db.execute(
                    "INSERT INTO service_tools (service_id, tool_name) VALUES (?, ?)",
                    (service_id, tool),
                )
        if tags is not None:
            await self.db.execute("DELETE FROM service_tags WHERE service_id = ?", (service_id,))
            for tag in tags:
                await self.db.execute(
                    "INSERT INTO service_tags (service_id, tag) VALUES (?, ?)",
                    (service_id, tag),
                )

        await self.db.commit()
        return True

    async def search_services(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        max_cost: float | None = None,
        pricing_model: str | None = None,
        status: str = "active",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search services with filters. Returns enriched service dicts."""
        conditions: list[str] = ["s.status = ?"]
        params: list[Any] = [status]

        if query:
            conditions.append("(s.name LIKE ? OR s.description LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])

        if category:
            conditions.append("s.category = ?")
            params.append(category)

        if tags:
            placeholders = ", ".join("?" for _ in tags)
            conditions.append(f"s.id IN (SELECT service_id FROM service_tags WHERE tag IN ({placeholders}))")
            params.extend(tags)

        if pricing_model:
            conditions.append("json_extract(s.pricing_json, '$.model') = ?")
            params.append(pricing_model)

        if max_cost is not None:
            conditions.append("CAST(json_extract(s.pricing_json, '$.cost') AS REAL) <= ?")
            params.append(max_cost)

        where = " AND ".join(conditions)
        sql = f"""
            SELECT DISTINCT s.* FROM services s
            WHERE {where}
            ORDER BY s.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        cursor = await self.db.execute(sql, params)  # nosemgrep: sqlalchemy-execute-raw-query
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            svc = await self._enrich_service(dict(row))
            results.append(svc)
        return results

    async def list_categories(self) -> list[dict[str, Any]]:
        """List all categories with service counts."""
        cursor = await self.db.execute(
            """SELECT category, COUNT(*) as count
               FROM services WHERE status = 'active'
               GROUP BY category ORDER BY count DESC"""
        )
        rows = await cursor.fetchall()
        return [{"category": r["category"], "count": r["count"]} for r in rows]

    async def count_search_results(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        max_cost: float | None = None,
        pricing_model: str | None = None,
        status: str = "active",
    ) -> int:
        """Count total matching services (ignoring LIMIT/OFFSET) for pagination."""
        conditions: list[str] = ["s.status = ?"]
        params: list[Any] = [status]

        if query:
            conditions.append("(s.name LIKE ? OR s.description LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like])

        if category:
            conditions.append("s.category = ?")
            params.append(category)

        if tags:
            placeholders = ", ".join("?" for _ in tags)
            conditions.append(f"s.id IN (SELECT service_id FROM service_tags WHERE tag IN ({placeholders}))")
            params.extend(tags)

        if pricing_model:
            conditions.append("json_extract(s.pricing_json, '$.model') = ?")
            params.append(pricing_model)

        if max_cost is not None:
            conditions.append("CAST(json_extract(s.pricing_json, '$.cost') AS REAL) <= ?")
            params.append(max_cost)

        where = " AND ".join(conditions)
        sql = f"SELECT COUNT(DISTINCT s.id) as cnt FROM services s WHERE {where}"

        cursor = await self.db.execute(sql, params)  # nosemgrep: sqlalchemy-execute-raw-query
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def count_services(self, status: str = "active") -> int:
        """Count services with given status."""
        cursor = await self.db.execute("SELECT COUNT(*) as cnt FROM services WHERE status = ?", (status,))
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def add_rating(self, service_id: str, agent_id: str, rating: int, review: str = "") -> None:
        """Add or update a rating for a service."""
        import time

        await self.db.execute(
            "INSERT INTO service_ratings (service_id, agent_id, rating, review, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(service_id, agent_id) DO UPDATE SET rating = ?, review = ?, created_at = ?",
            (service_id, agent_id, rating, review, time.time(), rating, review, time.time()),
        )
        await self.db.commit()

    async def get_ratings(self, service_id: str, limit: int = 20) -> dict[str, Any]:
        """Get ratings summary and list for a service."""
        cursor = await self.db.execute(
            "SELECT AVG(rating) as avg_rating, COUNT(*) as cnt FROM service_ratings WHERE service_id = ?",
            (service_id,),
        )
        row = await cursor.fetchone()
        avg_rating = round(row["avg_rating"], 2) if row["avg_rating"] is not None else 0.0
        count = row["cnt"] if row else 0

        cursor2 = await self.db.execute(
            "SELECT agent_id, rating, review, created_at FROM service_ratings "
            "WHERE service_id = ? ORDER BY created_at DESC LIMIT ?",
            (service_id, limit),
        )
        rows = await cursor2.fetchall()
        ratings = [dict(r) for r in rows]
        return {"average_rating": avg_rating, "count": count, "ratings": ratings}

    async def insert_suggestion(self, agent_id: str, category: str, message: str) -> int:
        """Insert a platform suggestion. Returns the suggestion ID."""
        import time

        cursor = await self.db.execute(
            "INSERT INTO suggestions (agent_id, category, message, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, category, message, time.time()),
        )
        await self.db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    async def get_suggestions(
        self,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get suggestions, optionally filtered by category."""
        query = "SELECT * FROM suggestions WHERE 1=1"
        params: list[Any] = []
        if category is not None:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self.db.execute(query, params)
        return [dict(r) for r in await cursor.fetchall()]

    async def _enrich_service(self, svc: dict[str, Any]) -> dict[str, Any]:
        """Add tools and tags to a service dict."""
        sid = svc["id"]
        cursor = await self.db.execute("SELECT tool_name FROM service_tools WHERE service_id = ?", (sid,))
        tools = [r["tool_name"] for r in await cursor.fetchall()]

        cursor = await self.db.execute("SELECT tag FROM service_tags WHERE service_id = ?", (sid,))
        tags = [r["tag"] for r in await cursor.fetchall()]

        svc["tools"] = tools
        svc["tags"] = tags
        return svc
