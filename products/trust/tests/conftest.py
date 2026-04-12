"""Shared fixtures for trust & reputation tests."""

from __future__ import annotations

import os
import sys
import time

import pytest

# Route shared_src registration + tmp_db through the single base module.
_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "tests"))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from _conftest_base import register_shared_src, tmp_db  # noqa: F401, E402

register_shared_src(__file__)

from src.api import TrustAPI  # noqa: E402
from src.models import Server, TransportType  # noqa: E402
from src.scorer import ScoreEngine  # noqa: E402
from src.storage import StorageBackend  # noqa: E402


@pytest.fixture
async def storage(tmp_db):  # noqa: F811  (pytest fixture chaining, not redefinition)
    """Yield a connected StorageBackend, closed after test."""
    backend = StorageBackend(dsn=tmp_db)
    await backend.connect()
    yield backend
    await backend.close()


@pytest.fixture
async def scorer(storage):
    """Yield a ScoreEngine backed by test storage."""
    return ScoreEngine(storage=storage)


@pytest.fixture
async def api(storage, scorer):
    """Yield a TrustAPI backed by test storage and scorer."""
    return TrustAPI(storage=storage, scorer=scorer)


@pytest.fixture
async def sample_server(storage):
    """Register and return a sample server for testing."""
    server = Server(
        id="test-server-001",
        name="Test MCP Server",
        url="https://example.com/mcp",
        transport_type=TransportType.HTTP,
        registered_at=time.time(),
        last_probed_at=None,
    )
    return await storage.register_server(server)
