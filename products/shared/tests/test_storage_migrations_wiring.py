"""Wiring guardrail: every product storage module must call
``apply_column_migrations`` before running its schema DDL.

This is a structural test. The `apply_column_migrations` helper is the
single choke-point that prevents audit finding C2 (``OperationalError:
no such column`` on DBs created by an older code version). If a future
refactor silently drops the call in one of the product storage
backends, the test suite must catch it.

We check two things per file:

1. The import is present.
2. The call is present *inside* the ``connect()`` method body, and
   appears **before** the DDL call (``executescript(_SCHEMA)`` or
   ``_create_tables()``). Order matters — running the migrations after
   executescript defeats the purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# (module_path_from_repo_root, ddl_call_source_substring)
_STORAGE_MODULES = [
    ("products/payments/src/storage.py", "executescript(_SCHEMA)"),
    ("products/identity/src/storage.py", "executescript(_SCHEMA)"),
    ("products/messaging/src/storage.py", "executescript(_SCHEMA)"),
    ("products/trust/src/storage.py", "executescript(_SCHEMA)"),
    ("products/marketplace/src/storage.py", "_create_tables"),
]


def _connect_source(path: Path) -> str:
    """Return the source of the connect() method in the first class that
    defines one. Product storage files all have exactly one.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.AsyncFunctionDef) and item.name == "connect":
                return ast.unparse(item)
    raise AssertionError(f"No connect() method found in {path}")


def test_all_storage_modules_call_apply_column_migrations() -> None:
    for rel_path, ddl_call in _STORAGE_MODULES:
        path = REPO_ROOT / rel_path
        assert path.exists(), f"{rel_path} missing — audit C2 fix regressed?"

        full = path.read_text()
        assert "apply_column_migrations" in full, (
            f"{rel_path}: shared column-migration helper not imported. "
            "This reverts audit finding C2. Restore the import and the "
            "connect() call before merging."
        )

        connect_src = _connect_source(path)
        assert "apply_column_migrations" in connect_src, (
            f"{rel_path}: apply_column_migrations is imported but the "
            "connect() method no longer calls it. The migration helper "
            "only works if it runs on every connection."
        )

        # Order check: migration call must precede DDL call.
        mig_pos = connect_src.find("apply_column_migrations(")
        ddl_pos = connect_src.find(ddl_call)
        assert mig_pos != -1, f"{rel_path}: apply_column_migrations call not found"
        assert ddl_pos != -1, f"{rel_path}: DDL call '{ddl_call}' not found"
        assert mig_pos < ddl_pos, (
            f"{rel_path}: apply_column_migrations must run BEFORE "
            f"'{ddl_call}'. Running migrations after the DDL defeats "
            "the purpose — executescript will still see the column "
            "mismatch first."
        )


def test_all_storage_modules_declare_column_migrations_attribute() -> None:
    """Every storage class must declare ``_COLUMN_MIGRATIONS`` (even if
    empty) so new contributors see the hook and know where to register
    new columns."""
    for rel_path, _ in _STORAGE_MODULES:
        path = REPO_ROOT / rel_path
        src = path.read_text()
        assert "_COLUMN_MIGRATIONS" in src, (
            f"{rel_path}: missing _COLUMN_MIGRATIONS class attribute. "
            "Declare it as an empty tuple — it is the registration "
            "point for future column additions and documents the hook."
        )
