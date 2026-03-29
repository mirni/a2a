"""MCP tool handlers for PostgreSQL connector."""

import json
import logging
import time
from typing import Any

from src.models import (
    DescribeTableParams,
    ExecuteParams,
    ExplainQueryParams,
    ListSchemasParams,
    ListTablesParams,
    QueryParams,
)

logger = logging.getLogger("a2a.postgres")

# Shared module imports — these come from the shared package via PYTHONPATH
# We use lazy imports to avoid module name collisions
_audit = None
_errors = None


def _get_audit():
    global _audit
    if _audit is None:
        import importlib

        _audit = importlib.import_module("shared.src.audit_log")
    return _audit


def _get_errors():
    global _errors
    if _errors is None:
        import importlib

        _errors = importlib.import_module("shared.src.errors")
    return _errors


async def handle_query(client, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a read-only SELECT query."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = QueryParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        rows = await client.query(
            sql=validated.sql,
            params=validated.params,
            timeout=validated.timeout_seconds,
            max_rows=validated.max_rows,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="query",
            connector="postgres",
            params={"sql": validated.sql, "param_count": len(validated.params)},
            result_summary=f"returned {len(rows)} rows",
            duration_ms=duration,
        )
        return {
            "rows": _serialize_rows(rows),
            "row_count": len(rows),
            "truncated": len(rows) >= validated.max_rows,
        }
    except PermissionError as e:
        raise errors.ConnectorError(str(e), code="READ_ONLY", retryable=False) from e
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="query",
            connector="postgres",
            params={"sql": validated.sql},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_execute(client, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a write statement (INSERT/UPDATE/DELETE)."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = ExecuteParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e), details={"params": params}) from e

    try:
        result = await client.execute(
            sql=validated.sql,
            params=validated.params,
            timeout=validated.timeout_seconds,
        )
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="execute",
            connector="postgres",
            params={"sql": validated.sql, "param_count": len(validated.params)},
            result_summary=result,
            duration_ms=duration,
        )
        return {"status": result}
    except PermissionError as e:
        raise errors.ConnectorError(str(e), code="READ_ONLY", retryable=False) from e
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        audit.log_operation(
            operation="execute",
            connector="postgres",
            params={"sql": validated.sql},
            error=str(e),
            duration_ms=duration,
        )
        raise


async def handle_list_tables(client, params: dict[str, Any]) -> dict[str, Any]:
    """List tables in a schema."""
    audit = _get_audit()
    start = time.monotonic()
    validated = ListTablesParams(**params)
    tables = await client.fetch_schema_info(validated.schema_name)
    duration = (time.monotonic() - start) * 1000
    audit.log_operation(
        operation="list_tables",
        connector="postgres",
        params={"schema": validated.schema_name},
        result_summary=f"found {len(tables)} tables",
        duration_ms=duration,
    )
    return {"tables": tables, "count": len(tables)}


async def handle_describe_table(client, params: dict[str, Any]) -> dict[str, Any]:
    """Describe a table's columns."""
    errors = _get_errors()
    audit = _get_audit()
    start = time.monotonic()
    try:
        validated = DescribeTableParams(**params)
    except Exception as e:
        raise errors.ValidationError(str(e)) from e

    columns = await client.describe_table(validated.table_name, validated.schema_name)
    duration = (time.monotonic() - start) * 1000
    audit.log_operation(
        operation="describe_table",
        connector="postgres",
        params={"table": validated.table_name, "schema": validated.schema_name},
        result_summary=f"found {len(columns)} columns",
        duration_ms=duration,
    )
    return {
        "table": validated.table_name,
        "schema": validated.schema_name,
        "columns": columns,
        "column_count": len(columns),
    }


async def handle_explain_query(client, params: dict[str, Any]) -> dict[str, Any]:
    """Get query execution plan."""
    audit = _get_audit()
    start = time.monotonic()
    validated = ExplainQueryParams(**params)
    plan = await client.explain_query(
        sql=validated.sql,
        params=validated.params,
        analyze=validated.analyze,
    )
    duration = (time.monotonic() - start) * 1000
    audit.log_operation(
        operation="explain_query",
        connector="postgres",
        params={"sql": validated.sql, "analyze": validated.analyze},
        result_summary="plan generated",
        duration_ms=duration,
    )
    return {"plan": plan}


async def handle_list_schemas(client, params: dict[str, Any]) -> dict[str, Any]:
    """List available database schemas."""
    audit = _get_audit()
    start = time.monotonic()
    ListSchemasParams(**params)  # validate (consistent interface)
    schemas = await client.list_schemas()
    duration = (time.monotonic() - start) * 1000
    audit.log_operation(
        operation="list_schemas",
        connector="postgres",
        result_summary=f"found {len(schemas)} schemas",
        duration_ms=duration,
    )
    return {"schemas": schemas, "count": len(schemas)}


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize row values to JSON-safe types."""
    serialized = []
    for row in rows:
        clean = {}
        for key, value in row.items():
            if hasattr(value, "isoformat"):
                clean[key] = value.isoformat()
            elif isinstance(value, bytes):
                clean[key] = value.hex()
            elif isinstance(value, (dict, list)):
                clean[key] = value
            else:
                try:
                    json.dumps(value)
                    clean[key] = value
                except (TypeError, ValueError):
                    clean[key] = str(value)
        serialized.append(clean)
    return serialized
