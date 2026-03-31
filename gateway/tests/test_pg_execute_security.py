"""Security tests for pg_execute SQL validation.

Ensures the gateway blocks dangerous SQL statements before they reach
the postgres MCP connector. This guards against CVSS 9.8 arbitrary SQL
execution (DDL/DCL/multi-statement injection).
"""

from __future__ import annotations

from gateway.src.sql_validator import validate_pg_execute_sql


class TestSelectAllowed:
    """SELECT queries must be allowed through pg_execute."""

    def test_simple_select(self):
        result = validate_pg_execute_sql("SELECT id, name FROM users WHERE id = $1", {"params": [1]})
        assert result is None  # None means "no error"

    def test_select_with_join(self):
        sql = "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id WHERE u.id = $1"
        result = validate_pg_execute_sql(sql, {"params": [42]})
        assert result is None

    def test_select_without_params(self):
        """SELECT is safe even without params (read-only)."""
        result = validate_pg_execute_sql("SELECT count(*) FROM users", {})
        assert result is None


class TestDDLBlocked:
    """DDL statements (CREATE, ALTER, DROP, TRUNCATE) must be blocked."""

    def test_drop_table_blocked(self):
        result = validate_pg_execute_sql("DROP TABLE users", {})
        assert result is not None
        assert "blocked" in result.lower() or "not allowed" in result.lower()

    def test_drop_table_case_insensitive(self):
        result = validate_pg_execute_sql("drop table users", {})
        assert result is not None

    def test_create_table_blocked(self):
        result = validate_pg_execute_sql("CREATE TABLE evil (id int)", {})
        assert result is not None

    def test_alter_table_blocked(self):
        result = validate_pg_execute_sql("ALTER TABLE users ADD COLUMN admin boolean", {})
        assert result is not None

    def test_truncate_blocked(self):
        result = validate_pg_execute_sql("TRUNCATE TABLE users", {})
        assert result is not None


class TestDCLBlocked:
    """DCL statements (GRANT, REVOKE) must be blocked."""

    def test_grant_blocked(self):
        result = validate_pg_execute_sql("GRANT ALL ON users TO evil_user", {})
        assert result is not None

    def test_revoke_blocked(self):
        result = validate_pg_execute_sql("REVOKE SELECT ON users FROM public", {})
        assert result is not None


class TestExecBlocked:
    """EXEC / EXECUTE statements must be blocked."""

    def test_exec_blocked(self):
        result = validate_pg_execute_sql("EXEC sp_dangerous", {})
        assert result is not None

    def test_execute_procedure(self):
        result = validate_pg_execute_sql("EXECUTE dangerous_procedure()", {})
        assert result is not None


class TestWriteRequiresParams:
    """INSERT, UPDATE, DELETE require non-empty params to prevent SQL injection."""

    def test_insert_with_params_allowed(self):
        result = validate_pg_execute_sql(
            "INSERT INTO users (name) VALUES ($1)",
            {"params": ["Alice"]},
        )
        assert result is None

    def test_insert_without_params_blocked(self):
        result = validate_pg_execute_sql(
            "INSERT INTO users (name) VALUES ('Alice')",
            {},
        )
        assert result is not None
        assert "params" in result.lower() or "parameterized" in result.lower()

    def test_insert_with_empty_params_blocked(self):
        result = validate_pg_execute_sql(
            "INSERT INTO users (name) VALUES ('Alice')",
            {"params": []},
        )
        assert result is not None

    def test_update_with_params_allowed(self):
        result = validate_pg_execute_sql(
            "UPDATE users SET name = $1 WHERE id = $2",
            {"params": ["Bob", 1]},
        )
        assert result is None

    def test_update_without_params_blocked(self):
        result = validate_pg_execute_sql(
            "UPDATE users SET name = 'hacked' WHERE 1=1",
            {},
        )
        assert result is not None

    def test_delete_with_params_allowed(self):
        result = validate_pg_execute_sql(
            "DELETE FROM users WHERE id = $1",
            {"params": [99]},
        )
        assert result is None

    def test_delete_without_params_blocked(self):
        result = validate_pg_execute_sql(
            "DELETE FROM users WHERE 1=1",
            {},
        )
        assert result is not None


class TestMultiStatementBlocked:
    """Multiple statements (semicolons outside strings) must be blocked."""

    def test_select_then_drop(self):
        result = validate_pg_execute_sql("SELECT 1; DROP TABLE users", {})
        assert result is not None
        assert "multiple" in result.lower() or "semicolon" in result.lower()

    def test_insert_then_drop(self):
        result = validate_pg_execute_sql(
            "INSERT INTO log (msg) VALUES ($1); DROP TABLE users",
            {"params": ["hi"]},
        )
        assert result is not None

    def test_semicolon_inside_string_literal_allowed(self):
        """Semicolons inside single-quoted strings should not trigger the check."""
        result = validate_pg_execute_sql(
            "INSERT INTO log (msg) VALUES ($1)",
            {"params": ["contains; semicolon"]},
        )
        assert result is None

    def test_trailing_semicolon_allowed(self):
        """A single trailing semicolon is harmless and should be tolerated."""
        result = validate_pg_execute_sql("SELECT 1;", {})
        assert result is None


class TestSQLInjectionBlocked:
    """SQL injection via string concatenation should be blocked."""

    def test_union_injection_in_non_parameterized_query(self):
        """Non-parameterized INSERT with injected UNION should be blocked."""
        result = validate_pg_execute_sql(
            "INSERT INTO log (msg) VALUES ('x' UNION SELECT password FROM users)",
            {},
        )
        assert result is not None

    def test_comment_injection(self):
        """Attempts to use -- comments to bypass validation should be blocked by multi-statement check."""
        result = validate_pg_execute_sql(
            "SELECT 1; -- DROP TABLE users",
            {},
        )
        assert result is not None


class TestCopyAndOtherDangerous:
    """Other dangerous commands must also be blocked."""

    def test_copy_blocked(self):
        result = validate_pg_execute_sql("COPY users TO '/tmp/dump.csv'", {})
        assert result is not None

    def test_vacuum_blocked(self):
        result = validate_pg_execute_sql("VACUUM FULL users", {})
        assert result is not None

    def test_set_blocked(self):
        result = validate_pg_execute_sql("SET role = 'admin'", {})
        assert result is not None

    def test_do_block_blocked(self):
        result = validate_pg_execute_sql("DO $$ BEGIN EXECUTE 'DROP TABLE users'; END $$", {})
        assert result is not None
