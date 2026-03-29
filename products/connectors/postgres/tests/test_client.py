"""Tests for PostgreSQL client (connection config and read-only enforcement)."""

import os
from unittest.mock import MagicMock, patch

import pytest
from src.client import PostgresClient
from src.models import ConnectionConfig


class TestConfigFromEnv:
    def test_reads_env_vars(self):
        env = {
            "PG_HOST": "db.example.com",
            "PG_PORT": "5433",
            "PG_DATABASE": "mydb",
            "PG_USER": "admin",
            "PG_PASSWORD": "secret",
            "PG_SSL": "true",
            "PG_READ_ONLY": "false",
        }
        with patch.dict(os.environ, env):
            config = PostgresClient._config_from_env()
            assert config.host == "db.example.com"
            assert config.port == 5433
            assert config.database == "mydb"
            assert config.user == "admin"
            assert config.password == "secret"
            assert config.ssl is True
            assert config.read_only is False

    def test_defaults(self):
        env = {"PG_DATABASE": "testdb", "PG_USER": "testuser"}
        with patch.dict(os.environ, env, clear=True):
            config = PostgresClient._config_from_env()
            assert config.host == "localhost"
            assert config.port == 5432
            assert config.read_only is True


class TestReadOnlyEnforcement:
    @pytest.mark.asyncio
    async def test_execute_blocked_in_read_only(self):
        config = ConnectionConfig(database="db", user="u", read_only=True)
        client = PostgresClient(config=config)
        # Fake a pool so we don't get "not connected" error
        client._pool = MagicMock()

        with pytest.raises(PermissionError, match="read-only mode"):
            await client.execute("INSERT INTO users (name) VALUES ($1)", ["test"])

    @pytest.mark.asyncio
    async def test_not_connected_error(self):
        config = ConnectionConfig(database="db", user="u")
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.query("SELECT 1")

    @pytest.mark.asyncio
    async def test_not_connected_execute(self):
        config = ConnectionConfig(database="db", user="u", read_only=False)
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.execute("INSERT INTO x (a) VALUES ($1)", [1])

    @pytest.mark.asyncio
    async def test_not_connected_schema_info(self):
        config = ConnectionConfig(database="db", user="u")
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.fetch_schema_info()

    @pytest.mark.asyncio
    async def test_not_connected_describe(self):
        config = ConnectionConfig(database="db", user="u")
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.describe_table("users")

    @pytest.mark.asyncio
    async def test_not_connected_explain(self):
        config = ConnectionConfig(database="db", user="u")
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.explain_query("SELECT 1")

    @pytest.mark.asyncio
    async def test_not_connected_list_schemas(self):
        config = ConnectionConfig(database="db", user="u")
        client = PostgresClient(config=config)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.list_schemas()
