"""Shared fixtures and bootstrap helpers for product test suites.

Every product's ``tests/conftest.py`` has historically duplicated the
same bootstrap block that registers ``shared_src`` as a virtual package
and declares a ``tmp_db`` fixture. This module is the single source
of truth those conftests import from, eliminating ~200 lines of copy-
paste and making the registration idempotent / observable from tests.

Usage (from a product's ``conftest.py``)::

    # products/<name>/tests/conftest.py
    import os
    import sys

    _BASE = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "shared", "tests")
    )
    if _BASE not in sys.path:
        sys.path.insert(0, _BASE)

    from _conftest_base import register_shared_src  # noqa: E402
    register_shared_src(__file__)

    # Re-export the common fixtures you want pytest to see:
    from _conftest_base import tmp_db  # noqa: F401, E402

Keep product-specific fixtures (``storage``, ``api``, ``engine`` …) in
each product's own ``conftest.py``; this module only covers what is
genuinely identical across every product.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

__all__ = ["register_shared_src", "tmp_db", "SHARED_SRC_DIR"]

# Canonical path to products/shared/src (resolved once, read by tests).
SHARED_SRC_DIR: Path = Path(__file__).resolve().parent.parent / "src"


def register_shared_src(caller_file: str | None = None) -> None:
    """Register ``shared_src`` as a virtual package pointing at ``products/shared/src``.

    Idempotent: safe to call from every product conftest without
    stomping on an existing registration. ``caller_file`` is accepted
    for backwards compatibility with call sites that want to pass
    ``__file__``; it is no longer needed because this module knows
    where ``products/shared/src`` lives.

    This reproduces the exact behaviour that every product conftest
    had inlined, so we can delete those copies without breaking
    cross-product imports like ``from shared_src.db_security import …``.
    """
    shared_src_dir = str(SHARED_SRC_DIR)
    if not SHARED_SRC_DIR.is_dir():  # pragma: no cover - defensive
        raise RuntimeError(
            f"SHARED_SRC_DIR does not exist: {shared_src_dir}. "
            "register_shared_src is being called from an unexpected location."
        )

    existing = sys.modules.get("shared_src")
    if existing is not None:
        # Already registered — make sure the path is correct. We
        # deliberately do not overwrite so the first-registered
        # copy wins.
        paths = getattr(existing, "__path__", [])
        if shared_src_dir not in paths:  # pragma: no cover - defensive
            # Different path already claimed the name; surface the conflict.
            raise RuntimeError(
                f"shared_src is already registered with __path__={paths!r}, "
                f"but expected {shared_src_dir!r}. "
                "Two product conftests disagree on where shared_src lives."
            )
        return

    pkg = types.ModuleType("shared_src")
    pkg.__path__ = [shared_src_dir]  # type: ignore[attr-defined]
    pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = pkg


@pytest.fixture
async def tmp_db() -> AsyncIterator[str]:
    """Yield a temporary SQLite DSN; cleans up the file afterwards.

    Extracted from billing/trust/paywall/… conftests, which all had
    an identical copy of this fixture. Product conftests can import
    and re-export this symbol to make it visible to their tests::

        from _conftest_base import tmp_db  # noqa: F401
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield f"sqlite:///{path}"
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
