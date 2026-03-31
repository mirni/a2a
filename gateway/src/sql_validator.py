"""SQL statement validator for pg_execute security hardening.

Restricts pg_execute to parameterized DML (SELECT, INSERT, UPDATE, DELETE)
and blocks all DDL, DCL, and other dangerous statements.

This module closes CVSS 9.8 arbitrary SQL execution via the pg_execute tool.
"""

from __future__ import annotations

import re

# Allowed top-level SQL command prefixes (case-insensitive).
_ALLOWED_COMMANDS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE", "WITH"})

# Blocked command prefixes — DDL, DCL, and other dangerous operations.
_BLOCKED_COMMANDS = frozenset({
    "CREATE",
    "ALTER",
    "DROP",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "COPY",
    "VACUUM",
    "ANALYZE",
    "CLUSTER",
    "REINDEX",
    "SET",
    "RESET",
    "SHOW",
    "LISTEN",
    "NOTIFY",
    "PREPARE",
    "DEALLOCATE",
    "REASSIGN",
    "COMMENT",
    "SECURITY",
    "LOCK",
    "DO",
    "CALL",
    "LOAD",
    "IMPORT",
    "DISCARD",
    "REFRESH",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT",
    "RELEASE",
    "START",
    "END",
    "ABORT",
})

# Write commands that require non-empty params for parameterization safety.
_WRITE_COMMANDS = frozenset({"INSERT", "UPDATE", "DELETE"})


def _extract_command(sql: str) -> str:
    """Extract the first SQL keyword from a statement.

    Returns the uppercased first word.
    """
    stripped = sql.strip()
    # Skip leading comments (-- or /* ... */)
    while stripped.startswith("--"):
        newline = stripped.find("\n")
        if newline == -1:
            return ""
        stripped = stripped[newline + 1:].strip()
    while stripped.startswith("/*"):
        end = stripped.find("*/")
        if end == -1:
            return ""
        stripped = stripped[end + 2:].strip()

    match = re.match(r"[A-Za-z_]+", stripped)
    if match:
        return match.group(0).upper()
    return ""


def _contains_semicolon_outside_strings(sql: str) -> bool:
    """Check if SQL contains semicolons outside of single-quoted string literals.

    Strips a single trailing semicolon first (harmless).
    """
    stripped = sql.strip().rstrip(";").strip()

    in_string = False
    for char in stripped:
        if char == "'":
            in_string = not in_string
        elif char == ";" and not in_string:
            return True
    return False


def validate_pg_execute_sql(sql: str, params_dict: dict) -> str | None:
    """Validate a SQL statement for the pg_execute tool.

    Args:
        sql: The SQL statement to validate.
        params_dict: The full params dict from the tool call (may contain "params" key).

    Returns:
        None if the statement is safe to execute.
        An error message string if the statement is blocked.
    """
    if not sql or not sql.strip():
        return "Empty SQL statement is not allowed."

    # 1. Check for multiple statements (semicolons outside strings)
    if _contains_semicolon_outside_strings(sql):
        return (
            "Multiple statements are not allowed. "
            "Only single SQL statements can be executed."
        )

    # 2. Extract the command type
    command = _extract_command(sql)
    if not command:
        return "Could not determine SQL command type. Statement is not allowed."

    # 3. Block explicitly dangerous commands
    if command in _BLOCKED_COMMANDS:
        return (
            f"SQL command '{command}' is not allowed. "
            f"Only SELECT, INSERT, UPDATE, and DELETE are permitted."
        )

    # 4. Check against allowed list
    if command not in _ALLOWED_COMMANDS:
        return (
            f"SQL command '{command}' is not allowed. "
            f"Only SELECT, INSERT, UPDATE, and DELETE are permitted."
        )

    # 5. Write commands require non-empty params for parameterization safety
    if command in _WRITE_COMMANDS:
        params_list = params_dict.get("params", [])
        if not params_list:
            return (
                f"{command} statements must use parameterized queries "
                f"(non-empty params list required). "
                f"Use $1, $2, ... placeholders with corresponding params."
            )

    return None
