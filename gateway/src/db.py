"""
Database DSN parsing and connection configuration.

Supports SQLite and PostgreSQL backends.

PostgreSQL support requires the ``asyncpg`` package::

    pip install asyncpg

asyncpg is an **optional** dependency — it is only needed when a PostgreSQL
DSN is supplied.  SQLite connections work with the standard library alone.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def parse_dsn(dsn: str) -> dict:
    """Parse a database DSN string into its component parts.

    Parameters
    ----------
    dsn:
        A connection string.  Recognised schemes:

        * ``sqlite:///path/to/db.db``
        * ``postgresql://user:pass@host:port/dbname``
        * ``postgres://user:pass@host:port/dbname``  (alias)

    Returns
    -------
    dict
        Parsed components keyed by backend type.

    Raises
    ------
    ValueError
        If *dsn* does not match a supported scheme.
    """
    if dsn.startswith("sqlite:///"):
        path = dsn[len("sqlite://") :]  # keep the leading '/'
        return {"backend": "sqlite", "path": path}

    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        parsed = urlparse(dsn)
        return {
            "backend": "postgresql",
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "database": (parsed.path or "/").lstrip("/") or None,
            "user": parsed.username,
            "password": parsed.password,
        }

    raise ValueError(
        f"Unknown DSN format: {dsn!r}. Expected a DSN starting with 'sqlite:///', 'postgresql://', or 'postgres://'."
    )


def get_connection_config(dsn: str) -> dict:
    """Return recommended connection-pool settings for *dsn*.

    Parameters
    ----------
    dsn:
        A connection string accepted by :func:`parse_dsn`.

    Returns
    -------
    dict
        Configuration dict suitable for initialising a connection pool.

        * **SQLite** — ``pool_size`` is always ``1`` (SQLite does not
          support concurrent writers).
        * **PostgreSQL** — pool boundaries and statement-cache size are
          read from environment variables so operators can tune without
          code changes:

          =============================  ===========
          Environment variable           Default
          =============================  ===========
          ``PG_MIN_POOL``                ``2``
          ``PG_MAX_POOL``                ``10``
          ``PG_STMT_CACHE``              ``100``
          =============================  ===========
    """
    info = parse_dsn(dsn)

    if info["backend"] == "sqlite":
        return {
            "backend": "sqlite",
            "path": info["path"],
            "pool_size": 1,
        }

    # PostgreSQL
    return {
        "backend": "postgresql",
        "dsn": dsn,
        "min_pool_size": int(os.environ.get("PG_MIN_POOL", "2")),
        "max_pool_size": int(os.environ.get("PG_MAX_POOL", "10")),
        "statement_cache_size": int(os.environ.get("PG_STMT_CACHE", "100")),
    }
