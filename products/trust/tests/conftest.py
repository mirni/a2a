"""Shared fixtures for trust & reputation tests."""

from __future__ import annotations

import os
import sys
import tempfile
import time
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
from src.scorer import ScoreEngine
from src.api import TrustAPI
from src.models import Server, TransportType


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
