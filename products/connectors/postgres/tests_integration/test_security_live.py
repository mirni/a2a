"""Live DB tests: SQL injection resistance and read-only enforcement.

These prove — against a real Postgres — that:
  - Parameterized queries neutralize injection attempts ($1 binding)
  - asyncpg rejects multi-statement queries at the wire protocol
  - Read-only mode is enforced at the Python layer
  - The `LIMIT {max_rows}` template interpolation on client.py:99 cannot
    be abused because max_rows is typed as int by pydantic

If any test here FAILS, that is a security finding — document it and fix
before launch.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest


@pytest.mark.asyncio
async def test_injection_via_param_is_neutralized(rw_client) -> None:
    """Classic injection payload in a param value must be treated as literal."""
    payload = "'; DROP TABLE public.users; --"
    rows = await rw_client.query(
        "SELECT id FROM public.users WHERE email = $1",
        [payload],
    )
    # Must return no rows (no user with that email) and NOT drop the table
    assert rows == []

    # Prove table still exists + has rows
    rows = await rw_client.query("SELECT COUNT(*)::int AS c FROM public.users", [])
    assert rows[0]["c"] >= 50


@pytest.mark.asyncio
async def test_injection_via_param_in_like_is_neutralized(rw_client) -> None:
    """LIKE pattern injection must also be neutralized by parameterization."""
    payload = "%'; DELETE FROM public.users; --"
    rows = await rw_client.query(
        "SELECT id FROM public.users WHERE email LIKE $1",
        [payload],
    )
    assert rows == []
    rows = await rw_client.query("SELECT COUNT(*)::int AS c FROM public.users", [])
    assert rows[0]["c"] >= 50


@pytest.mark.asyncio
async def test_multi_statement_blocked_by_asyncpg(rw_client) -> None:
    """asyncpg's extended query protocol rejects multiple statements."""
    with pytest.raises((asyncpg.PostgresSyntaxError, asyncpg.InterfaceError, Exception)) as exc_info:
        await rw_client.query("SELECT 1; SELECT 2", [])
    msg = str(exc_info.value).lower()
    assert "multiple" in msg or "cannot insert multiple" in msg or "syntax" in msg or "prepared statement" in msg


@pytest.mark.asyncio
async def test_readonly_blocks_writes_at_python_layer(ro_client) -> None:
    """Python-side read_only=True flag rejects execute() before SQL sent."""
    with pytest.raises(PermissionError):
        await ro_client.execute(
            "INSERT INTO public.users (email, name) VALUES ($1, $2)",
            [f"test+ro+{uuid.uuid4().hex[:6]}@example.com", "ro"],
        )


@pytest.mark.asyncio
async def test_max_rows_cannot_inject_sql(rw_client) -> None:
    """max_rows is typed as int in pydantic — string injection can't reach the
    f-string on client.py:99. This test confirms that directly calling
    client.query with a string max_rows is rejected by Postgres syntax check
    (not silently executed). Defense-in-depth verification.
    """
    # Directly bypass the pydantic layer and push a malicious string in.
    # Postgres must reject it — this proves the final safety net.
    with pytest.raises(Exception):
        await rw_client.query(
            "SELECT id FROM public.users",
            [],
            max_rows="10; DROP TABLE public.users --",  # type: ignore[arg-type]
        )
    # Verify the table survives
    rows = await rw_client.query("SELECT COUNT(*)::int AS c FROM public.users", [])
    assert rows[0]["c"] >= 50


@pytest.mark.asyncio
async def test_max_rows_via_validator_is_int_clamped() -> None:
    """QueryParams validates max_rows as int <= 10000."""
    from pydantic import ValidationError
    from src.models import QueryParams

    # String that looks like int but contains injection is rejected by pydantic
    with pytest.raises(ValidationError):
        QueryParams(sql="SELECT 1", max_rows="1; DROP TABLE users --")  # type: ignore[arg-type]

    # Too-large value is clamped/rejected
    with pytest.raises(ValidationError):
        QueryParams(sql="SELECT 1", max_rows=999999)

    # Negative value rejected
    with pytest.raises(ValidationError):
        QueryParams(sql="SELECT 1", max_rows=-1)


@pytest.mark.asyncio
async def test_timeout_prevents_runaway_and_releases_connection(rw_client) -> None:
    """A timed-out query must return the connection to the pool (no leak)."""
    import asyncio as _asyncio

    with pytest.raises((asyncpg.QueryCanceledError, _asyncio.TimeoutError)):
        await rw_client.query("SELECT pg_sleep(10)", [], timeout=0.5)

    # Pool must still have connections available — next query succeeds
    rows = await rw_client.query("SELECT 1 AS x", [])
    assert rows == [{"x": 1}]


@pytest.mark.asyncio
async def test_select_in_execute_params_blocked_by_model() -> None:
    """ExecuteParams.must_be_write rejects non-DML at validation time."""
    from pydantic import ValidationError
    from src.models import ExecuteParams

    with pytest.raises(ValidationError):
        ExecuteParams(sql="SELECT * FROM users", params=[])
    with pytest.raises(ValidationError):
        ExecuteParams(sql="DROP TABLE users", params=[])
    with pytest.raises(ValidationError):
        ExecuteParams(sql="CREATE TABLE x (y int)", params=[])


@pytest.mark.asyncio
async def test_query_semicolon_injection_in_model() -> None:
    """QueryParams.no_semicolon_injection strips trailing ; but rejects extra."""
    from pydantic import ValidationError
    from src.models import QueryParams

    # Trailing semicolon OK (stripped)
    q = QueryParams(sql="SELECT 1;", params=[])
    assert ";" not in q.sql

    # Embedded semicolon rejected
    with pytest.raises(ValidationError):
        QueryParams(sql="SELECT 1; SELECT 2", params=[])


@pytest.mark.asyncio
async def test_identifier_validator_blocks_quote_injection() -> None:
    """DescribeTableParams rejects identifiers with quotes/spaces."""
    from pydantic import ValidationError
    from src.models import DescribeTableParams

    for bad in ['users" OR "1"="1', "users; DROP TABLE users", "users' --"]:
        with pytest.raises(ValidationError):
            DescribeTableParams(table_name=bad)
