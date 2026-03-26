"""Shared fixtures for billing tests."""

from __future__ import annotations

import os
import tempfile

import pytest

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
    await backend.connect()
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
    await t.connect()
    yield t
    await t.close()
