#!/usr/bin/env python3
"""Helper for scripts/migrate_db.sh — list products, run migrations, validate.

Deliberately avoids importing bootstrap() or any product module that pulls in
heavy dependencies (aiosqlite, pydantic, etc.) at the top level.  Only the
migrate module and aiosqlite are imported, and only when actually needed.

Usage:
    python3 migrate_db_helper.py list-products
    python3 migrate_db_helper.py migrate <db_path> <product>
    python3 migrate_db_helper.py validate <db_path> <product>
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Lightweight import helpers — no bootstrap(), no product __init__.py
# ---------------------------------------------------------------------------


def _ensure_shared_src():
    """Register shared_src package so migrate.py can be imported."""
    if "shared_src" in sys.modules:
        return
    shared_dir = os.path.join(REPO_ROOT, "products", "shared", "src")
    pkg = types.ModuleType("shared_src")
    pkg.__path__ = [shared_dir]
    pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = pkg


def _import_migrate():
    """Import and return the shared_src.migrate module."""
    _ensure_shared_src()
    return importlib.import_module("shared_src.migrate")


def _import_aiosqlite():
    """Import and return aiosqlite."""
    return importlib.import_module("aiosqlite")


def _load_migrations(product_name: str):
    """Load _MIGRATIONS from a product's storage.py without importing the class.

    Reads only the Migration objects defined in the _MIGRATIONS tuple,
    avoiding the full StorageBackend import (which pulls in aiosqlite
    at class-definition time via BaseStorage).
    """
    migrate = _import_migrate()
    Migration = migrate.Migration

    product_dir = os.path.join(REPO_ROOT, "products", product_name, "src")
    storage_py = os.path.join(product_dir, "storage.py")

    if not os.path.isfile(storage_py):
        return ()

    # Read the file and extract _MIGRATIONS by exec-ing only the tuple
    # definition with Migration available in the namespace.
    with open(storage_py) as f:
        source = f.read()

    # Find the _MIGRATIONS assignment block
    # We exec the whole module in a restricted namespace that stubs out
    # everything except what we need.
    ns = {"Migration": Migration, "__builtins__": {}}
    # Extract lines from "_MIGRATIONS" to the closing ")"
    lines = source.split("\n")
    collecting = False
    mig_lines = []
    paren_depth = 0
    for line in lines:
        if not collecting and "_MIGRATIONS" in line and "=" in line:
            collecting = True
            mig_lines.append(line)
            paren_depth += line.count("(") - line.count(")")
            continue
        if collecting:
            mig_lines.append(line)
            paren_depth += line.count("(") - line.count(")")
            if paren_depth <= 0:
                break

    if not mig_lines:
        return ()

    # Dedent — the assignment is inside a class body
    import textwrap

    code = textwrap.dedent("\n".join(mig_lines))
    exec(code, ns)  # noqa: S102
    return ns.get("_MIGRATIONS", ())


# ---------------------------------------------------------------------------
# Product registry
# ---------------------------------------------------------------------------

_PRODUCTS = [
    {
        "name": "billing",
        "env_var": "BILLING_DB",
        "default_path": "/var/lib/a2a/billing.db",
    },
]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_list_products():
    """Print product:env_var:default_path:expected_version for each product."""
    for p in _PRODUCTS:
        migrations = _load_migrations(p["name"])
        if not migrations:
            continue
        expected = max(m.version for m in migrations)
        print(f"{p['name']}:{p['env_var']}:{p['default_path']}:{expected}")


async def cmd_migrate(db_path: str, product_name: str):
    """Run pending migrations on db_path for the given product."""
    migrations = _load_migrations(product_name)
    if not migrations:
        print(f"No migrations for {product_name}")
        return

    migrate = _import_migrate()
    aiosqlite = _import_aiosqlite()

    db = await aiosqlite.connect(db_path)
    try:
        applied = await migrate.run_migrations(db, migrations)
        version = await migrate.get_current_version(db)
        print(f"OK: applied={applied} version={version}")
    finally:
        await db.close()


async def cmd_validate(db_path: str, product_name: str):
    """Validate db integrity + schema version for the given product."""
    migrations = _load_migrations(product_name)
    expected = max(m.version for m in migrations) if migrations else 0

    migrate = _import_migrate()
    aiosqlite = _import_aiosqlite()

    db = await aiosqlite.connect(db_path)
    try:
        cursor = await db.execute("PRAGMA integrity_check")
        result = await cursor.fetchone()
        if result[0] != "ok":
            print(f"FAIL: integrity_check returned {result[0]}", file=sys.stderr)
            sys.exit(1)

        version = await migrate.get_current_version(db)
        if version != expected:
            print(
                f"FAIL: version={version} expected={expected}",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"OK: integrity=ok version={version}")
    finally:
        await db.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "list-products":
        cmd_list_products()
    elif cmd == "migrate" and len(sys.argv) == 4:
        asyncio.run(cmd_migrate(sys.argv[2], sys.argv[3]))
    elif cmd == "validate" and len(sys.argv) == 4:
        asyncio.run(cmd_validate(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
