#!/usr/bin/env python3
"""Helper for scripts/migrate_db.sh — list products, run migrations, validate.

Usage:
    python3 migrate_db_helper.py list-products
    python3 migrate_db_helper.py migrate <db_path> <product>
    python3 migrate_db_helper.py validate <db_path> <product>
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure repo root and products are importable
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)

# Bootstrap cross-product imports
from gateway.src.bootstrap import bootstrap  # noqa: E402
bootstrap()

import aiosqlite  # noqa: E402
from shared_src.migrate import get_current_version, run_migrations  # noqa: E402


# ---------------------------------------------------------------------------
# Product registry: (prefix, env_var, default_path, storage_class_path)
# ---------------------------------------------------------------------------

_PRODUCTS = [
    {
        "name": "billing",
        "env_var": "BILLING_DB",
        "default_path": "/var/lib/a2a/billing.db",
        "module": "billing_src.storage",
        "class": "StorageBackend",
    },
]


def _get_storage_class(product: dict):
    """Import and return the StorageBackend class for a product."""
    mod = sys.modules.get(product["module"])
    if mod is None:
        raise ImportError(f"Module {product['module']} not found after bootstrap")
    return getattr(mod, product["class"])


def cmd_list_products():
    """Print product:env_var:default_path:expected_version for each product."""
    for p in _PRODUCTS:
        cls = _get_storage_class(p)
        if not cls._MIGRATIONS:
            continue
        expected = max(m.version for m in cls._MIGRATIONS)
        print(f"{p['name']}:{p['env_var']}:{p['default_path']}:{expected}")


async def cmd_migrate(db_path: str, product_name: str):
    """Run pending migrations on db_path for the given product."""
    product = next((p for p in _PRODUCTS if p["name"] == product_name), None)
    if product is None:
        print(f"ERROR: unknown product '{product_name}'", file=sys.stderr)
        sys.exit(1)

    cls = _get_storage_class(product)
    if not cls._MIGRATIONS:
        print(f"No migrations for {product_name}")
        return

    db = await aiosqlite.connect(db_path)
    try:
        applied = await run_migrations(db, cls._MIGRATIONS)
        version = await get_current_version(db)
        print(f"OK: applied={applied} version={version}")
    finally:
        await db.close()


async def cmd_validate(db_path: str, product_name: str):
    """Validate db integrity + schema version for the given product."""
    product = next((p for p in _PRODUCTS if p["name"] == product_name), None)
    if product is None:
        print(f"ERROR: unknown product '{product_name}'", file=sys.stderr)
        sys.exit(1)

    cls = _get_storage_class(product)
    expected = max(m.version for m in cls._MIGRATIONS) if cls._MIGRATIONS else 0

    db = await aiosqlite.connect(db_path)
    try:
        # Integrity check
        cursor = await db.execute("PRAGMA integrity_check")
        result = await cursor.fetchone()
        if result[0] != "ok":
            print(f"FAIL: integrity_check returned {result[0]}", file=sys.stderr)
            sys.exit(1)

        # Version check
        version = await get_current_version(db)
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
