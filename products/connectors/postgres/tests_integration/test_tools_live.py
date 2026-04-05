"""Live DB tests: MCP TOOL_HANDLERS via a real PostgresClient.

These exercise the handler layer (src.tools) — the same code the MCP stdio
server calls when the gateway proxies a pg_* request.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_tool_query_returns_rows_and_count(rw_client) -> None:
    from src.tools import handle_query

    result = await handle_query(
        rw_client,
        {"sql": "SELECT id, email FROM public.users ORDER BY id", "params": [], "max_rows": 10},
    )
    assert "rows" in result and "row_count" in result
    assert result["row_count"] == 10
    assert result["truncated"] is True
    assert all("id" in r and "email" in r for r in result["rows"])


@pytest.mark.asyncio
async def test_tool_query_not_truncated_when_below_max(rw_client) -> None:
    from src.tools import handle_query

    result = await handle_query(
        rw_client,
        {"sql": "SELECT id FROM public.users WHERE id <= 3", "params": [], "max_rows": 100},
    )
    assert result["row_count"] == 3
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_tool_query_serializes_timestamptz_to_iso_string(rw_client) -> None:
    from src.tools import handle_query

    result = await handle_query(
        rw_client,
        {"sql": "SELECT created_at FROM public.users WHERE id = $1", "params": [1]},
    )
    assert isinstance(result["rows"][0]["created_at"], str)
    # ISO-8601 format with timezone offset
    assert "T" in result["rows"][0]["created_at"]


@pytest.mark.asyncio
async def test_tool_query_rejects_invalid_params_shape(rw_client) -> None:
    """Pydantic ValidationError -> ValidationError."""
    from src.tools import handle_query

    with pytest.raises(Exception) as exc_info:
        await handle_query(rw_client, {"sql": "SELECT 1", "max_rows": -1})
    assert "max_rows" in str(exc_info.value).lower() or "validation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tool_execute_insert_roundtrip(rw_client, clean_users_slate) -> None:
    from src.tools import handle_execute, handle_query

    email = f"test+{uuid.uuid4().hex[:8]}@example.com"
    result = await handle_execute(
        rw_client,
        {
            "sql": "INSERT INTO public.users (email, name) VALUES ($1, $2)",
            "params": [email, "tool test"],
        },
    )
    assert "INSERT" in result["status"]

    verify = await handle_query(
        rw_client,
        {"sql": "SELECT email FROM public.users WHERE email = $1", "params": [email]},
    )
    assert verify["row_count"] == 1


@pytest.mark.asyncio
async def test_tool_execute_rejects_select(rw_client) -> None:
    """ExecuteParams.must_be_write must reject SELECT even at handler level."""
    from src.tools import handle_execute

    with pytest.raises(Exception) as exc_info:
        await handle_execute(rw_client, {"sql": "SELECT 1", "params": []})
    assert "INSERT" in str(exc_info.value) or "write" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tool_execute_blocked_in_readonly_client(ro_client) -> None:
    from src.tools import handle_execute

    with pytest.raises(Exception) as exc_info:
        await handle_execute(
            ro_client,
            {
                "sql": "INSERT INTO public.users (email, name) VALUES ($1, $2)",
                "params": ["test+ro@example.com", "ro"],
            },
        )
    assert "read-only" in str(exc_info.value).lower() or "READ_ONLY" in str(exc_info.value)


@pytest.mark.asyncio
async def test_tool_list_tables_public(rw_client) -> None:
    from src.tools import handle_list_tables

    result = await handle_list_tables(rw_client, {"schema_name": "public"})
    names = {t["table_name"] for t in result["tables"]}
    assert {"users", "orders", "products", "big_table"}.issubset(names)
    assert result["count"] >= 4


@pytest.mark.asyncio
async def test_tool_list_tables_custom_schema(rw_client) -> None:
    from src.tools import handle_list_tables

    result = await handle_list_tables(rw_client, {"schema_name": "test_schema"})
    assert any(t["table_name"] == "audit_log" for t in result["tables"])


@pytest.mark.asyncio
async def test_tool_describe_table(rw_client) -> None:
    from src.tools import handle_describe_table

    result = await handle_describe_table(rw_client, {"table_name": "products", "schema_name": "public"})
    assert result["column_count"] == 4
    names = {c["column_name"] for c in result["columns"]}
    assert {"id", "sku", "name", "price"} == names


@pytest.mark.asyncio
async def test_tool_describe_table_rejects_bad_identifier(rw_client) -> None:
    """DescribeTableParams.must_be_identifier rejects non-alphanumeric."""
    from src.tools import handle_describe_table

    with pytest.raises(Exception) as exc_info:
        await handle_describe_table(
            rw_client,
            {"table_name": "users; DROP TABLE users --", "schema_name": "public"},
        )
    assert "identifier" in str(exc_info.value).lower() or "validation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tool_list_schemas(rw_client) -> None:
    from src.tools import handle_list_schemas

    result = await handle_list_schemas(rw_client, {})
    assert "public" in result["schemas"]
    assert "test_schema" in result["schemas"]
    assert "pg_catalog" not in result["schemas"]


@pytest.mark.asyncio
async def test_tool_explain_query_basic(rw_client) -> None:
    from src.tools import handle_explain_query

    result = await handle_explain_query(
        rw_client,
        {"sql": "SELECT * FROM public.users WHERE id = $1", "params": [1], "analyze": False},
    )
    assert "Scan" in result["plan"]


@pytest.mark.asyncio
async def test_tool_explain_analyze_works_on_readonly(ro_client) -> None:
    """EXPLAIN ANALYZE on SELECT must work even in read-only mode."""
    from src.tools import handle_explain_query

    result = await handle_explain_query(
        ro_client,
        {"sql": "SELECT id FROM public.users", "params": [], "analyze": True},
    )
    assert "actual time=" in result["plan"]
