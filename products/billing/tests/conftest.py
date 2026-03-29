"""Shared fixtures for billing tests."""

from __future__ import annotations

import os
import sys
import tempfile
import types

import pytest

# Register shared_src so cross-product imports (db_security) resolve
_shared_src_dir = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src")
)
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

from src.storage import StorageBackend
from src.events import BillingEventStream
from src.policies import RatePolicyManager
from src.tracker import UsageTracker
from src.wallet import Wallet


@pytest.fixture
async def tmp_db():
    """Yield a temporary database path, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield f"sqlite:///{path}"
    os.unlink(path)


@pytest.fixture
async def storage(tmp_db):
    """Yield a connected StorageBackend, closed after test."""
    backend = StorageBackend(dsn=tmp_db)
    await backend.connect(apply_migrations=True)
    yield backend
    await backend.close()


@pytest.fixture
async def wallet(storage):
    """Yield a Wallet instance backed by the test storage."""
    return Wallet(storage=storage)


@pytest.fixture
async def policies(storage):
    """Yield a RatePolicyManager instance backed by the test storage."""
    return RatePolicyManager(storage=storage)


@pytest.fixture
async def event_stream(storage):
    """Yield a BillingEventStream instance backed by the test storage."""
    return BillingEventStream(storage=storage)


@pytest.fixture
async def tracker(tmp_db):
    """Yield a connected UsageTracker, closed after test."""
    t = UsageTracker(storage=tmp_db)
    await t.connect(apply_migrations=True)
    yield t
    await t.close()
