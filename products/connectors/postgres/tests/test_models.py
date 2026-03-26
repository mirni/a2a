"""Tests for PostgreSQL connector input validation models."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.models import (
    ConnectionConfig,
    DescribeTableParams,
    ExecuteParams,
    ListTablesParams,
    QueryParams,
)


class TestQueryParams:
    def test_valid_select(self):
        q = QueryParams(sql="SELECT * FROM users WHERE id = $1", params=[1])
        assert q.sql == "SELECT * FROM users WHERE id = $1"

    def test_valid_with_cte(self):
        q = QueryParams(sql="WITH active AS (SELECT * FROM users) SELECT * FROM active")
        assert q.sql.startswith("WITH")

    def test_rejects_insert(self):
        with pytest.raises(PydanticValidationError, match="only SELECT"):
            QueryParams(sql="INSERT INTO users (name) VALUES ($1)", params=["test"])

    def test_rejects_delete(self):
        with pytest.raises(PydanticValidationError, match="only SELECT"):
            QueryParams(sql="DELETE FROM users WHERE id = $1", params=[1])

    def test_rejects_multiple_statements(self):
        with pytest.raises(PydanticValidationError, match="Multiple statements"):
            QueryParams(sql="SELECT 1; DROP TABLE users")

    def test_strips_trailing_semicolon(self):
        q = QueryParams(sql="SELECT 1;")
        assert q.sql == "SELECT 1"

    def test_default_timeout(self):
        q = QueryParams(sql="SELECT 1")
        assert q.timeout_seconds == 30.0

    def test_default_max_rows(self):
        q = QueryParams(sql="SELECT 1")
        assert q.max_rows == 1000

    def test_max_rows_limit(self):
        with pytest.raises(PydanticValidationError):
            QueryParams(sql="SELECT 1", max_rows=50000)

    def test_timeout_limit(self):
        with pytest.raises(PydanticValidationError):
            QueryParams(sql="SELECT 1", timeout_seconds=500)


class TestExecuteParams:
    def test_valid_insert(self):
        e = ExecuteParams(sql="INSERT INTO users (name) VALUES ($1)", params=["test"])
        assert e.sql.startswith("INSERT")

    def test_valid_update(self):
        e = ExecuteParams(sql="UPDATE users SET name = $1 WHERE id = $2", params=["new", 1])
        assert e.sql.startswith("UPDATE")

    def test_valid_delete(self):
        e = ExecuteParams(sql="DELETE FROM users WHERE id = $1", params=[1])
        assert e.sql.startswith("DELETE")

    def test_rejects_select(self):
        with pytest.raises(PydanticValidationError, match="only INSERT"):
            ExecuteParams(sql="SELECT * FROM users")

    def test_rejects_drop(self):
        with pytest.raises(PydanticValidationError, match="only INSERT"):
            ExecuteParams(sql="DROP TABLE users")

    def test_rejects_multiple_statements(self):
        with pytest.raises(PydanticValidationError, match="Multiple statements"):
            ExecuteParams(sql="INSERT INTO users (name) VALUES ('a'); DELETE FROM users")


class TestDescribeTableParams:
    def test_valid(self):
        d = DescribeTableParams(table_name="users")
        assert d.table_name == "users"
        assert d.schema_name == "public"

    def test_valid_with_underscore(self):
        d = DescribeTableParams(table_name="user_accounts", schema_name="app_data")
        assert d.table_name == "user_accounts"

    def test_rejects_sql_injection(self):
        with pytest.raises(PydanticValidationError, match="Invalid identifier"):
            DescribeTableParams(table_name="users; DROP TABLE users")

    def test_rejects_special_chars(self):
        with pytest.raises(PydanticValidationError, match="Invalid identifier"):
            DescribeTableParams(table_name="users--")


class TestListTablesParams:
    def test_default_schema(self):
        lt = ListTablesParams()
        assert lt.schema_name == "public"


class TestConnectionConfig:
    def test_defaults(self):
        c = ConnectionConfig(database="mydb", user="myuser")
        assert c.host == "localhost"
        assert c.port == 5432
        assert c.read_only is True
        assert c.min_pool_size == 2
        assert c.max_pool_size == 10

    def test_invalid_port(self):
        with pytest.raises(PydanticValidationError):
            ConnectionConfig(database="db", user="u", port=0)
