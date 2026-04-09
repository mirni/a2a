"""Shared fixtures for gatekeeper product tests."""

from __future__ import annotations

import os
import sys
import types

import pytest_asyncio

# Register shared_src so cross-product imports resolve
_shared_src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src"))
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

# Ensure project root and gatekeeper product are importable
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for p in [_project_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from products.gatekeeper.src.api import GatekeeperAPI
from products.gatekeeper.src.storage import GatekeeperStorage


@pytest_asyncio.fixture
async def storage(tmp_path):
    """Provide a connected GatekeeperStorage backed by a temporary SQLite database."""
    dsn = f"sqlite:///{tmp_path}/gatekeeper_test.db"
    s = GatekeeperStorage(dsn=dsn)
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def api(storage):
    """Provide a GatekeeperAPI instance backed by temporary storage (no verifier)."""
    return GatekeeperAPI(storage=storage)
