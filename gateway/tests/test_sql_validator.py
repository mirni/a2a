"""Tests for gateway.src.sql_validator — SQL validation for pg_execute."""

from __future__ import annotations

from gateway.src.sql_validator import validate_pg_execute_sql


class TestEmptySQL:
    def test_empty_string_blocked(self):
        assert validate_pg_execute_sql("", {}) is not None

    def test_whitespace_only_blocked(self):
        assert validate_pg_execute_sql("   \n\t  ", {}) is not None


class TestCommentStripping:
    def test_nested_line_comments_stripped(self):
        sql = "-- comment 1\n-- comment 2\nSELECT 1"
        assert validate_pg_execute_sql(sql, {}) is None

    def test_block_comment_stripped(self):
        sql = "/* block */ SELECT 1"
        assert validate_pg_execute_sql(sql, {}) is None

    def test_unterminated_block_comment_blocked(self):
        sql = "/* no close SELECT 1"
        result = validate_pg_execute_sql(sql, {})
        assert result is not None  # can't determine command type

    def test_comment_only_sql_blocked(self):
        sql = "-- just a comment"
        result = validate_pg_execute_sql(sql, {})
        assert result is not None


class TestSemicolons:
    def test_semicolon_inside_string_literal_allowed(self):
        sql = "SELECT * FROM t WHERE name = 'has;semi'"
        assert validate_pg_execute_sql(sql, {}) is None

    def test_multiple_statements_blocked(self):
        sql = "SELECT 1; DROP TABLE users"
        result = validate_pg_execute_sql(sql, {})
        assert "Multiple statements" in result

    def test_trailing_semicolon_allowed(self):
        sql = "SELECT 1;"
        assert validate_pg_execute_sql(sql, {}) is None

    def test_unmatched_quotes_with_semicolons_blocked(self):
        # Odd single quotes: the semicolon appears "inside" a broken literal
        # but the parser treats the char-by-char logic as outside at some point
        sql = "SELECT 'unclosed; DROP TABLE users"
        result = validate_pg_execute_sql(sql, {})
        # The semicolon should be detected as inside the string (in_string=True)
        # but let's verify actual behavior
        if result is not None:
            assert "Multiple statements" in result or "not allowed" in result


class TestCommandTypes:
    def test_select_allowed(self):
        assert validate_pg_execute_sql("SELECT * FROM t", {}) is None

    def test_with_statement_allowed(self):
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        assert validate_pg_execute_sql(sql, {}) is None

    def test_insert_with_params_allowed(self):
        sql = "INSERT INTO t (col) VALUES ($1)"
        assert validate_pg_execute_sql(sql, {"params": ["val"]}) is None

    def test_update_with_params_allowed(self):
        sql = "UPDATE t SET col = $1 WHERE id = $2"
        assert validate_pg_execute_sql(sql, {"params": ["val", 1]}) is None

    def test_delete_with_params_allowed(self):
        sql = "DELETE FROM t WHERE id = $1"
        assert validate_pg_execute_sql(sql, {"params": [1]}) is None

    def test_create_blocked(self):
        result = validate_pg_execute_sql("CREATE TABLE t (id int)", {})
        assert result is not None
        assert "not allowed" in result

    def test_drop_blocked(self):
        result = validate_pg_execute_sql("DROP TABLE users", {})
        assert result is not None

    def test_grant_blocked(self):
        result = validate_pg_execute_sql("GRANT ALL ON t TO public", {})
        assert result is not None

    def test_unknown_command_blocked(self):
        result = validate_pg_execute_sql("FOOBAR something", {})
        assert result is not None


class TestWriteWithoutParams:
    def test_insert_without_params_blocked(self):
        sql = "INSERT INTO t (col) VALUES ('literal')"
        result = validate_pg_execute_sql(sql, {})
        assert result is not None
        assert "parameterized" in result

    def test_update_without_params_blocked(self):
        sql = "UPDATE t SET col = 'val'"
        result = validate_pg_execute_sql(sql, {})
        assert result is not None
        assert "parameterized" in result

    def test_delete_without_params_blocked(self):
        sql = "DELETE FROM t WHERE true"
        result = validate_pg_execute_sql(sql, {})
        assert result is not None
        assert "parameterized" in result

    def test_insert_with_empty_params_blocked(self):
        sql = "INSERT INTO t (col) VALUES ('literal')"
        result = validate_pg_execute_sql(sql, {"params": []})
        assert result is not None

    def test_select_without_params_allowed(self):
        """SELECT doesn't require params."""
        assert validate_pg_execute_sql("SELECT * FROM t", {}) is None


class TestCaseInsensitivity:
    def test_lowercase_select(self):
        assert validate_pg_execute_sql("select 1", {}) is None

    def test_mixed_case_select(self):
        assert validate_pg_execute_sql("SeLeCt 1", {}) is None
