"""Unit + structural tests for ``_conftest_base`` consolidation.

This module pins:

* ``register_shared_src`` is idempotent and installs a virtual package
  with the correct ``__path__``.
* ``tmp_db`` yields a real, writable SQLite DSN and cleans up.
* Every product's ``tests/conftest.py`` imports from ``_conftest_base``
  and does **not** inline its own ``sys.modules["shared_src"]`` block.

The structural test catches any future contributor who reintroduces
the copy-paste bootstrap (which was the whole point of P1-1).
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from products.shared.tests import _conftest_base as base

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

PRODUCTS_WITH_SHARED_CONFTEST = (
    "billing",
    "identity",
    "messaging",
    "marketplace",
    "payments",
    "paywall",
    "trust",
)


# ---------------------------------------------------------------------------
# register_shared_src()
# ---------------------------------------------------------------------------


def test_register_shared_src_installs_virtual_package() -> None:
    """After calling, ``shared_src`` must be importable with correct path."""
    base.register_shared_src()
    mod = sys.modules.get("shared_src")
    assert mod is not None, "register_shared_src() did not install the package"
    assert str(base.SHARED_SRC_DIR) in mod.__path__  # type: ignore[attr-defined]


def test_register_shared_src_is_idempotent() -> None:
    """Second call must be a no-op (same object, no exception)."""
    base.register_shared_src()
    first = sys.modules["shared_src"]
    base.register_shared_src()  # should not raise
    assert sys.modules["shared_src"] is first


def test_shared_src_dir_points_at_real_directory() -> None:
    assert base.SHARED_SRC_DIR.is_dir(), f"{base.SHARED_SRC_DIR} not found"
    # Spot-check: known shared modules must exist.
    assert (base.SHARED_SRC_DIR / "db_security.py").is_file()
    assert (base.SHARED_SRC_DIR / "storage_migrations.py").is_file()


# ---------------------------------------------------------------------------
# tmp_db fixture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tmp_db_yields_writable_sqlite_dsn(tmp_db: str) -> None:
    """The fixture should yield a real SQLite DSN we can write to."""
    assert tmp_db.startswith("sqlite:///"), tmp_db
    path = tmp_db.removeprefix("sqlite:///")
    assert os.path.exists(path), f"{path} not created"
    # File is empty & writable (fixture created it with mkstemp).
    assert os.access(path, os.W_OK)


# ---------------------------------------------------------------------------
# Structural test: every product conftest must delegate to _conftest_base.
# ---------------------------------------------------------------------------


def _load_conftest_ast(product: str) -> ast.Module:
    path = REPO_ROOT / "products" / product / "tests" / "conftest.py"
    assert path.is_file(), f"conftest not found: {path}"
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_register_shared_src(tree: ast.Module) -> bool:
    """Return True iff the module imports ``register_shared_src`` from ``_conftest_base``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "_conftest_base":
            for alias in node.names:
                if alias.name == "register_shared_src":
                    return True
    return False


def _has_inline_shared_src_block(tree: ast.Module) -> bool:
    """Return True iff the module inlines the legacy ``sys.modules["shared_src"] = _pkg`` block."""
    for node in ast.walk(tree):
        # Look for `sys.modules["shared_src"] = <anything>`.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "modules"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "shared_src"
                ):
                    return True
    return False


@pytest.mark.parametrize("product", PRODUCTS_WITH_SHARED_CONFTEST)
def test_product_conftest_imports_register_shared_src(product: str) -> None:
    """Each product's conftest must route through ``_conftest_base``."""
    tree = _load_conftest_ast(product)
    assert _imports_register_shared_src(tree), (
        f"products/{product}/tests/conftest.py does not import "
        "register_shared_src from _conftest_base — the consolidation "
        "has been reverted."
    )


@pytest.mark.parametrize("product", PRODUCTS_WITH_SHARED_CONFTEST)
def test_product_conftest_has_no_inline_shared_src_block(product: str) -> None:
    """Structural guard: no raw ``sys.modules['shared_src'] = …`` allowed."""
    tree = _load_conftest_ast(product)
    assert not _has_inline_shared_src_block(tree), (
        f"products/{product}/tests/conftest.py contains an inline "
        "shared_src registration — delete it and use "
        "register_shared_src() from _conftest_base instead."
    )
