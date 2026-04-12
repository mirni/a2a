"""Shared fixtures for billing tests."""

from __future__ import annotations

import os
import sys

import pytest

# Route shared_src registration + tmp_db through the single base module.
_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "tests"))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from _conftest_base import register_shared_src, tmp_db  # noqa: F401, E402

register_shared_src(__file__)

from src.events import BillingEventStream  # noqa: E402
from src.policies import RatePolicyManager  # noqa: E402
from src.storage import StorageBackend  # noqa: E402
from src.tracker import UsageTracker  # noqa: E402
from src.wallet import Wallet  # noqa: E402


@pytest.fixture
async def storage(tmp_db):  # noqa: F811  (pytest fixture chaining, not redefinition)
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
async def tracker(tmp_db):  # noqa: F811
    """Yield a connected UsageTracker, closed after test."""
    t = UsageTracker(storage=tmp_db)
    await t.connect(apply_migrations=True)
    yield t
    await t.close()
