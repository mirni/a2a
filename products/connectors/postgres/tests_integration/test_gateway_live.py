"""E2E tests against a running gateway backed by the test Postgres DB.

These tests are SKIPPED unless A2A_GATEWAY_URL is set to a gateway instance
that has been configured with PG_* vars pointing at this harness's Postgres.

Run the gateway in a separate terminal first:
    export PG_HOST=localhost PG_PORT=5433 PG_DATABASE=a2a_connector_test \\
           PG_USER=a2a_test PG_PASSWORD=a2a_test_pwd_local_only PG_READ_ONLY=false
    HOME=/tmp /workdir/.venv/bin/python -m uvicorn gateway.main:app --port 8000
Then export A2A_GATEWAY_URL=http://localhost:8000 and run pytest.
"""

from __future__ import annotations

import os

import pytest

_GATEWAY_URL = os.environ.get("A2A_GATEWAY_URL")
_PRO_KEY = os.environ.get("A2A_PRO_KEY")
_FREE_KEY = os.environ.get("A2A_FREE_KEY")


if not _GATEWAY_URL:
    pytest.skip(
        "A2A_GATEWAY_URL not set — skipping gateway E2E tests. See module docstring for setup instructions.",
        allow_module_level=True,
    )

try:
    import httpx  # noqa: F401
except ImportError:
    pytest.skip("httpx not installed — skipping gateway E2E tests", allow_module_level=True)


@pytest.fixture
async def gw_client():
    """An httpx.AsyncClient targeting the gateway."""
    import httpx as _httpx

    async with _httpx.AsyncClient(base_url=_GATEWAY_URL, timeout=30.0) as c:
        yield c


def _require_pro_key() -> str:
    if not _PRO_KEY:
        pytest.skip("A2A_PRO_KEY not set")
    return _PRO_KEY


def _require_free_key() -> str:
    if not _FREE_KEY:
        pytest.skip("A2A_FREE_KEY not set")
    return _FREE_KEY


# ---------------------------------------------------------------------------
# Happy-path: pro-tier key → connector succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_pg_list_schemas_pro_ok(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={"tool": "pg_list_schemas", "params": {}},
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Response shape: either {"result": {...}} or flat depending on gateway version
    payload = body.get("result", body)
    schemas = payload.get("schemas") or payload.get("data", {}).get("schemas", [])
    assert "public" in schemas


@pytest.mark.asyncio
async def test_gateway_pg_list_tables_pro_ok(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={"tool": "pg_list_tables", "params": {"schema_name": "public"}},
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_gateway_pg_query_simple_select(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={
            "tool": "pg_query",
            "params": {"sql": "SELECT id, email FROM public.users ORDER BY id", "max_rows": 3},
        },
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Tier gate: free-tier key rejected with 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_pg_list_tables_free_rejected(gw_client) -> None:
    key = _require_free_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={"tool": "pg_list_tables", "params": {"schema_name": "public"}},
        headers={"X-API-Key": key},
    )
    assert resp.status_code == 403
    body = resp.json()
    # RFC 9457: type / status / title / detail
    assert body.get("status") == 403


# ---------------------------------------------------------------------------
# SQL validator gate: pg_execute with dangerous SQL rejected before DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gateway_pg_execute_rejects_drop(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={"tool": "pg_execute", "params": {"sql": "DROP TABLE public.users", "params": []}},
        headers={"X-API-Key": key},
    )
    # Validator should block before hitting DB — 400/422
    assert resp.status_code in (400, 422), resp.text


@pytest.mark.asyncio
async def test_gateway_pg_execute_rejects_create(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={"tool": "pg_execute", "params": {"sql": "CREATE TABLE evil (x int)", "params": []}},
        headers={"X-API-Key": key},
    )
    assert resp.status_code in (400, 422), resp.text


@pytest.mark.asyncio
async def test_gateway_pg_execute_rejects_multi_statement(gw_client) -> None:
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={
            "tool": "pg_execute",
            "params": {
                "sql": "INSERT INTO public.users (email) VALUES ($1); DELETE FROM public.users",
                "params": ["test+e2e@example.com"],
            },
        },
        headers={"X-API-Key": key},
    )
    assert resp.status_code in (400, 422), resp.text


@pytest.mark.asyncio
async def test_gateway_pg_execute_rejects_write_without_params(gw_client) -> None:
    """validate_pg_execute_sql requires non-empty params for INSERT/UPDATE/DELETE."""
    key = _require_pro_key()
    resp = await gw_client.post(
        "/v1/execute",
        json={
            "tool": "pg_execute",
            "params": {"sql": "INSERT INTO public.users (email) VALUES ('x@y.z')", "params": []},
        },
        headers={"X-API-Key": key},
    )
    assert resp.status_code in (400, 422), resp.text
