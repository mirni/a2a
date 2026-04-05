"""Live DB tests: PostgresClient connection, pool, and core query path."""

from __future__ import annotations

import asyncio
import uuid

import pytest

# ---------------------------------------------------------------------------
# Connection + pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_success(make_config) -> None:
    from src.client import PostgresClient

    client = PostgresClient(config=make_config())
    await client.connect()
    try:
        assert client._pool is not None
    finally:
        await client.close()
    assert client._pool is None


@pytest.mark.asyncio
async def test_connect_bad_host_fails_fast(make_config) -> None:
    from src.client import PostgresClient

    bad = make_config(host="127.0.0.1", port=1)  # closed port
    client = PostgresClient(config=bad)
    with pytest.raises(Exception):  # OSError/ConnectionError/asyncpg errors
        await asyncio.wait_for(client.connect(), timeout=5.0)


@pytest.mark.asyncio
async def test_connect_bad_credentials_fails(make_config) -> None:
    import asyncpg
    from src.client import PostgresClient

    bad = make_config(user="a2a_test", password="wrong_password")
    client = PostgresClient(config=bad)
    with pytest.raises(asyncpg.InvalidPasswordError):
        await client.connect()


@pytest.mark.asyncio
async def test_close_then_reconnect(make_config) -> None:
    from src.client import PostgresClient

    client = PostgresClient(config=make_config())
    await client.connect()
    rows = await client.query("SELECT 1 AS x", [])
    assert rows == [{"x": 1}]

    await client.close()
    with pytest.raises(RuntimeError, match="Not connected"):
        await client.query("SELECT 1", [])

    await client.connect()
    try:
        rows = await client.query("SELECT 2 AS x", [])
        assert rows == [{"x": 2}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_pool_reuses_connections(rw_client) -> None:
    """Fire 10 concurrent queries through the pool, all succeed."""
    tasks = [rw_client.query("SELECT $1::int AS v", [i]) for i in range(10)]
    results = await asyncio.gather(*tasks)
    assert [r[0]["v"] for r in results] == list(range(10))


# ---------------------------------------------------------------------------
# query() — SELECT path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_simple_select(rw_client) -> None:
    rows = await rw_client.query("SELECT 1 AS one, 'hi' AS greet", [])
    assert rows == [{"one": 1, "greet": "hi"}]


@pytest.mark.asyncio
async def test_query_with_params(rw_client) -> None:
    rows = await rw_client.query(
        "SELECT id, email FROM public.users WHERE email = $1",
        ["user1@example.com"],
    )
    assert len(rows) == 1
    assert rows[0]["email"] == "user1@example.com"


@pytest.mark.asyncio
async def test_query_max_rows_enforced(rw_client) -> None:
    rows = await rw_client.query(
        "SELECT id FROM public.big_table ORDER BY id",
        [],
        max_rows=50,
    )
    assert len(rows) == 50
    assert rows[0]["id"] == 1
    assert rows[-1]["id"] == 50


@pytest.mark.asyncio
async def test_query_empty_result(rw_client) -> None:
    rows = await rw_client.query(
        "SELECT id FROM public.users WHERE email = $1",
        ["nonexistent@example.com"],
    )
    assert rows == []


@pytest.mark.asyncio
async def test_query_timeout_fires(rw_client) -> None:
    import asyncpg

    with pytest.raises((asyncpg.QueryCanceledError, asyncio.TimeoutError)):
        await rw_client.query("SELECT pg_sleep(5)", [], timeout=0.5)


@pytest.mark.asyncio
async def test_query_null_values(rw_client) -> None:
    rows = await rw_client.query("SELECT NULL::int AS v, NULL::text AS t", [])
    assert rows == [{"v": None, "t": None}]


@pytest.mark.asyncio
async def test_query_types_jsonb_numeric_timestamptz(rw_client) -> None:
    from datetime import datetime
    from decimal import Decimal

    rows = await rw_client.query(
        "SELECT metadata, created_at FROM public.users WHERE id = $1",
        [1],
    )
    assert len(rows) == 1
    # JSONB -> dict
    assert isinstance(rows[0]["metadata"], dict)
    assert "tier" in rows[0]["metadata"]
    # TIMESTAMPTZ -> datetime
    assert isinstance(rows[0]["created_at"], datetime)

    rows2 = await rw_client.query(
        "SELECT price FROM public.products WHERE id = $1",
        [1],
    )
    assert isinstance(rows2[0]["price"], Decimal)


# ---------------------------------------------------------------------------
# execute() — write path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_blocked_in_readonly_mode(ro_client) -> None:
    with pytest.raises(PermissionError, match="read-only mode"):
        await ro_client.execute(
            "INSERT INTO public.users (email, name) VALUES ($1, $2)",
            ["test+blocked@example.com", "blocked"],
        )


@pytest.mark.asyncio
async def test_execute_insert_returns_status(rw_client, clean_users_slate) -> None:
    email = f"test+{uuid.uuid4().hex[:8]}@example.com"
    status = await rw_client.execute(
        "INSERT INTO public.users (email, name) VALUES ($1, $2)",
        [email, "test user"],
    )
    assert status.startswith("INSERT") and status.endswith(" 1")

    rows = await rw_client.query(
        "SELECT email FROM public.users WHERE email = $1",
        [email],
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_execute_update_returns_count(rw_client, clean_users_slate) -> None:
    email = f"test+{uuid.uuid4().hex[:8]}@example.com"
    await rw_client.execute(
        "INSERT INTO public.users (email, name) VALUES ($1, $2)",
        [email, "before"],
    )
    status = await rw_client.execute(
        "UPDATE public.users SET name = $1 WHERE email = $2",
        ["after", email],
    )
    assert status == "UPDATE 1"


@pytest.mark.asyncio
async def test_execute_delete_returns_count(rw_client, clean_users_slate) -> None:
    email = f"test+{uuid.uuid4().hex[:8]}@example.com"
    await rw_client.execute(
        "INSERT INTO public.users (email, name) VALUES ($1, $2)",
        [email, "temp"],
    )
    status = await rw_client.execute(
        "DELETE FROM public.users WHERE email = $1",
        [email],
    )
    assert status == "DELETE 1"


# ---------------------------------------------------------------------------
# fetch_schema_info / describe_table / list_schemas / explain_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_schema_info_public(rw_client) -> None:
    tables = await rw_client.fetch_schema_info("public")
    names = {t["table_name"] for t in tables}
    assert {"users", "orders", "products", "big_table"}.issubset(names)


@pytest.mark.asyncio
async def test_fetch_schema_info_custom_schema(rw_client) -> None:
    tables = await rw_client.fetch_schema_info("test_schema")
    assert any(t["table_name"] == "audit_log" for t in tables)


@pytest.mark.asyncio
async def test_fetch_schema_info_includes_views(rw_client) -> None:
    tables = await rw_client.fetch_schema_info("public")
    match = [t for t in tables if t["table_name"] == "orders_summary"]
    assert len(match) == 1
    assert match[0]["table_type"] == "VIEW"


@pytest.mark.asyncio
async def test_fetch_schema_info_empty(rw_client) -> None:
    assert await rw_client.fetch_schema_info("nonexistent_schema_xyz") == []


@pytest.mark.asyncio
async def test_describe_table_returns_columns(rw_client) -> None:
    cols = await rw_client.describe_table("users", "public")
    names = {c["column_name"] for c in cols}
    assert {"id", "email", "name", "active", "metadata", "created_at"} == names


@pytest.mark.asyncio
async def test_describe_table_nullable_flags(rw_client) -> None:
    cols = await rw_client.describe_table("users", "public")
    by_name = {c["column_name"]: c for c in cols}
    assert by_name["email"]["is_nullable"] == "NO"
    assert by_name["name"]["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_describe_table_defaults_for_serial(rw_client) -> None:
    cols = await rw_client.describe_table("users", "public")
    by_name = {c["column_name"]: c for c in cols}
    default = by_name["id"]["column_default"] or ""
    assert "nextval" in default


@pytest.mark.asyncio
async def test_describe_nonexistent_table(rw_client) -> None:
    assert await rw_client.describe_table("does_not_exist", "public") == []


@pytest.mark.asyncio
async def test_list_schemas_includes_custom_and_public(rw_client) -> None:
    schemas = await rw_client.list_schemas()
    assert "public" in schemas
    assert "test_schema" in schemas
    # System schemas excluded
    assert "pg_catalog" not in schemas
    assert "information_schema" not in schemas


@pytest.mark.asyncio
async def test_explain_basic_query(rw_client) -> None:
    plan = await rw_client.explain_query("SELECT * FROM public.users", [], analyze=False)
    assert "Scan" in plan  # Seq Scan / Index Scan / etc.


@pytest.mark.asyncio
async def test_explain_analyze_executes_and_has_timing(rw_client) -> None:
    plan = await rw_client.explain_query("SELECT * FROM public.users", [], analyze=True)
    # EXPLAIN ANALYZE output includes "actual time=" lines
    assert "actual time=" in plan
