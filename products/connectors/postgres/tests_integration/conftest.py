"""Shared fixtures for live-DB integration tests.

Skips all test_*_live.py modules if:
  - asyncpg is not installed, OR
  - PG_INTEGRATION_SKIP=1 is set, OR
  - the target Postgres cannot be reached within 2 seconds.

Default connection targets the docker-compose Postgres on localhost:5433.
Override via env vars: PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD.

The gateway E2E tests (test_gateway_live.py) additionally require
A2A_GATEWAY_URL to be set; they're skipped independently at module level.
"""

from __future__ import annotations

import os
import socket

import pytest

# Default env points to docker-compose db (see docker-compose.yml)
_DEFAULTS = {
    "PG_HOST": "localhost",
    "PG_PORT": "5433",
    "PG_DATABASE": "a2a_connector_test",
    "PG_USER": "a2a_test",
    "PG_PASSWORD": "a2a_test_pwd_local_only",
    "PG_READ_ONLY": "false",  # tests manage their own mode explicitly
}

for _k, _v in _DEFAULTS.items():
    os.environ.setdefault(_k, _v)


def _reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Collection-time skip: if prerequisites are missing, don't collect any of
# the live-DB test modules. collect_ignore_glob is read by pytest during
# collection and prevents import of the listed modules.
# ---------------------------------------------------------------------------

collect_ignore_glob: list[str] = []
_skip_reason: str | None = None

if os.environ.get("PG_INTEGRATION_SKIP") == "1":
    _skip_reason = "PG_INTEGRATION_SKIP=1"
else:
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        _skip_reason = "asyncpg not installed"
    else:
        _host = os.environ["PG_HOST"]
        _port = int(os.environ["PG_PORT"])
        if not _reachable(_host, _port):
            _skip_reason = f"Postgres not reachable at {_host}:{_port} — start docker-compose first"

if _skip_reason:
    # Skip every live-DB test module. test_gateway_live.py has its own
    # additional skip for A2A_GATEWAY_URL.
    collect_ignore_glob.extend(
        [
            "test_client_live.py",
            "test_tools_live.py",
            "test_security_live.py",
            "test_gateway_live.py",
        ]
    )

    # Emit the reason so CI logs show it
    print(f"[tests_integration] SKIP: {_skip_reason}")


# ---------------------------------------------------------------------------
# Fixtures (used by test modules only when collection proceeds)
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_PASSWORD")}


@pytest.fixture
def make_config():
    from src.models import ConnectionConfig

    def _make(**overrides) -> ConnectionConfig:
        base: dict[str, object] = {
            "host": os.environ["PG_HOST"],
            "port": int(os.environ["PG_PORT"]),
            "database": os.environ["PG_DATABASE"],
            "user": os.environ["PG_USER"],
            "password": os.environ["PG_PASSWORD"],
            "read_only": False,
        }
        base.update(overrides)
        return ConnectionConfig(**base)  # type: ignore[arg-type]

    return _make


@pytest.fixture
async def rw_client(make_config):
    from src.client import PostgresClient

    client = PostgresClient(config=make_config(read_only=False))
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def ro_client(make_config):
    from src.client import PostgresClient

    client = PostgresClient(config=make_config(read_only=True))
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


@pytest.fixture
async def clean_users_slate(rw_client):
    """Delete test-inserted rows (email LIKE 'test+%') after the test."""
    yield
    await rw_client.execute(
        "DELETE FROM public.users WHERE email LIKE $1",
        ["test+%"],
    )
