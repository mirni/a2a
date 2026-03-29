"""Tests for PostgreSQL tool handlers with mocked database client."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.tools import (
    _serialize_rows,
    handle_describe_table,
    handle_execute,
    handle_list_schemas,
    handle_list_tables,
    handle_query,
)


def make_mock_client(read_only=True):
    """Create a mock PostgresClient."""
    client = AsyncMock()
    client.config = MagicMock()
    client.config.read_only = read_only
    return client


class TestHandleQuery:
    @pytest.mark.asyncio
    async def test_valid_select(self):
        client = make_mock_client()
        client.query.return_value = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

        result = await handle_query(
            client,
            {
                "sql": "SELECT * FROM users WHERE id > $1",
                "params": [0],
            },
        )

        assert result["row_count"] == 2
        assert result["rows"][0]["name"] == "Alice"
        assert result["truncated"] is False
        client.query.assert_called_once()

    @pytest.mark.asyncio
    async def test_truncated_when_at_limit(self):
        client = make_mock_client()
        client.query.return_value = [{"id": i} for i in range(5)]

        result = await handle_query(
            client,
            {
                "sql": "SELECT * FROM big_table",
                "max_rows": 5,
            },
        )

        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_rejects_insert(self):
        client = make_mock_client()
        with pytest.raises(Exception, match="only SELECT"):
            await handle_query(client, {"sql": "INSERT INTO users (name) VALUES ($1)", "params": ["x"]})

    @pytest.mark.asyncio
    async def test_rejects_multiple_statements(self):
        client = make_mock_client()
        with pytest.raises(Exception, match="Multiple statements"):
            await handle_query(client, {"sql": "SELECT 1; DROP TABLE users"})


class TestHandleExecute:
    @pytest.mark.asyncio
    async def test_valid_insert(self):
        client = make_mock_client(read_only=False)
        client.execute.return_value = "INSERT 0 1"

        result = await handle_execute(
            client,
            {
                "sql": "INSERT INTO users (name) VALUES ($1)",
                "params": ["Alice"],
            },
        )

        assert result["status"] == "INSERT 0 1"

    @pytest.mark.asyncio
    async def test_rejects_select(self):
        client = make_mock_client(read_only=False)
        with pytest.raises(Exception, match="only INSERT"):
            await handle_execute(client, {"sql": "SELECT * FROM users"})

    @pytest.mark.asyncio
    async def test_rejects_drop(self):
        client = make_mock_client(read_only=False)
        with pytest.raises(Exception, match="only INSERT"):
            await handle_execute(client, {"sql": "DROP TABLE users"})


class TestHandleListTables:
    @pytest.mark.asyncio
    async def test_lists_tables(self):
        client = make_mock_client()
        client.fetch_schema_info.return_value = [
            {"table_name": "users", "table_type": "BASE TABLE"},
            {"table_name": "orders", "table_type": "BASE TABLE"},
        ]

        result = await handle_list_tables(client, {})

        assert result["count"] == 2
        assert result["tables"][0]["table_name"] == "users"

    @pytest.mark.asyncio
    async def test_custom_schema(self):
        client = make_mock_client()
        client.fetch_schema_info.return_value = []

        await handle_list_tables(client, {"schema_name": "analytics"})

        client.fetch_schema_info.assert_called_with("analytics")


class TestHandleDescribeTable:
    @pytest.mark.asyncio
    async def test_describes_columns(self):
        client = make_mock_client()
        client.describe_table.return_value = [
            {
                "column_name": "id",
                "data_type": "integer",
                "is_nullable": "NO",
                "column_default": "nextval('users_id_seq')",
                "character_maximum_length": None,
            },
            {
                "column_name": "name",
                "data_type": "character varying",
                "is_nullable": "YES",
                "column_default": None,
                "character_maximum_length": 255,
            },
        ]

        result = await handle_describe_table(client, {"table_name": "users"})

        assert result["column_count"] == 2
        assert result["columns"][0]["column_name"] == "id"

    @pytest.mark.asyncio
    async def test_rejects_sql_injection_table_name(self):
        client = make_mock_client()
        with pytest.raises(Exception, match="Invalid identifier"):
            await handle_describe_table(client, {"table_name": "users; DROP TABLE users"})


class TestHandleListSchemas:
    @pytest.mark.asyncio
    async def test_lists_schemas(self):
        client = make_mock_client()
        client.list_schemas.return_value = ["public", "analytics"]

        result = await handle_list_schemas(client, {})

        assert result["count"] == 2
        assert "public" in result["schemas"]


class TestSerializeRows:
    def test_handles_datetime(self):
        from datetime import datetime

        rows = [{"created": datetime(2026, 1, 1, 12, 0, 0)}]
        result = _serialize_rows(rows)
        assert result[0]["created"] == "2026-01-01T12:00:00"

    def test_handles_bytes(self):
        rows = [{"data": b"\x00\x01\x02"}]
        result = _serialize_rows(rows)
        assert result[0]["data"] == "000102"

    def test_handles_normal_types(self):
        rows = [{"id": 1, "name": "test", "active": True, "score": 3.14}]
        result = _serialize_rows(rows)
        assert result[0] == {"id": 1, "name": "test", "active": True, "score": 3.14}

    def test_handles_nested_dicts(self):
        rows = [{"meta": {"key": "value"}}]
        result = _serialize_rows(rows)
        assert result[0]["meta"] == {"key": "value"}
