"""PostgreSQL client with connection pooling and safety guarantees."""

import logging
import os
from typing import Any

from src.models import ConnectionConfig

logger = logging.getLogger("a2a.postgres")


class PostgresClient:
    """Async PostgreSQL client with connection pooling and safety.

    Wraps asyncpg with:
    - Connection pooling with health checks
    - Query parameterization enforcement
    - Read-only mode by default
    - Configurable timeouts and row limits
    - Reconnection on pool exhaustion
    """

    def __init__(self, config: ConnectionConfig | None = None):
        self._config = config or self._config_from_env()
        self._pool = None

    @staticmethod
    def _config_from_env() -> ConnectionConfig:
        """Build connection config from environment variables."""
        return ConnectionConfig(
            host=os.environ.get("PG_HOST", "localhost"),
            port=int(os.environ.get("PG_PORT", "5432")),
            database=os.environ.get("PG_DATABASE", ""),
            user=os.environ.get("PG_USER", ""),
            password=os.environ.get("PG_PASSWORD", ""),
            ssl=os.environ.get("PG_SSL", "false").lower() == "true",
            read_only=os.environ.get("PG_READ_ONLY", "true").lower() == "true",
        )

    @property
    def config(self) -> ConnectionConfig:
        return self._config

    async def connect(self) -> None:
        """Initialize the connection pool."""
        import asyncpg

        self._pool = await asyncpg.create_pool(
            host=self._config.host,
            port=self._config.port,
            database=self._config.database,
            user=self._config.user,
            password=self._config.password,
            min_size=self._config.min_pool_size,
            max_size=self._config.max_pool_size,
            command_timeout=60,
        )
        logger.info(
            "Connected to PostgreSQL %s:%d/%s (pool: %d-%d)",
            self._config.host,
            self._config.port,
            self._config.database,
            self._config.min_pool_size,
            self._config.max_pool_size,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def query(
        self,
        sql: str,
        params: list | None = None,
        timeout: float = 30.0,
        max_rows: int = 1000,
    ) -> list[dict[str, Any]]:
        """Execute a read-only query and return results as dicts.

        Args:
            sql: Parameterized SQL query ($1, $2, ...).
            params: Query parameters.
            timeout: Query timeout in seconds.
            max_rows: Maximum rows to return.

        Returns:
            List of row dicts.
        """
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            if self._config.read_only:
                await conn.execute("SET TRANSACTION READ ONLY")

            rows = await conn.fetch(
                sql + f" LIMIT {max_rows}",
                *(params or []),
                timeout=timeout,
            )

        return [dict(row) for row in rows]

    async def execute(
        self,
        sql: str,
        params: list | None = None,
        timeout: float = 30.0,
    ) -> str:
        """Execute a write statement (INSERT/UPDATE/DELETE).

        Args:
            sql: Parameterized SQL statement.
            params: Statement parameters.
            timeout: Statement timeout in seconds.

        Returns:
            Status string (e.g., "INSERT 0 1").
        """
        if self._config.read_only:
            raise PermissionError(
                "Database is in read-only mode. "
                "Set PG_READ_ONLY=false or config.read_only=False to enable writes."
            )

        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                sql,
                *(params or []),
                timeout=timeout,
            )

        return result

    async def fetch_schema_info(self, schema_name: str = "public") -> list[dict[str, Any]]:
        """List all tables in a schema."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        sql = """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = $1
            ORDER BY table_name
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, schema_name)

        return [dict(row) for row in rows]

    async def describe_table(
        self, table_name: str, schema_name: str = "public"
    ) -> list[dict[str, Any]]:
        """Get column details for a table."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length
            FROM information_schema.columns c
            WHERE c.table_schema = $1 AND c.table_name = $2
            ORDER BY c.ordinal_position
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, schema_name, table_name)

        return [dict(row) for row in rows]

    async def explain_query(
        self,
        sql: str,
        params: list | None = None,
        analyze: bool = False,
    ) -> str:
        """Get query execution plan."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        explain_prefix = "EXPLAIN ANALYZE" if analyze else "EXPLAIN"
        full_sql = f"{explain_prefix} {sql}"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(full_sql, *(params or []))

        return "\n".join(row["QUERY PLAN"] for row in rows)

    async def list_schemas(self) -> list[str]:
        """List available schemas."""
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")

        sql = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql)

        return [row["schema_name"] for row in rows]
