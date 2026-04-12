"""Shared fixtures for messaging product tests."""

from __future__ import annotations

import os
import sys

import pytest_asyncio

# Route shared_src registration through the single base module.
_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "tests"))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from _conftest_base import register_shared_src  # noqa: E402

register_shared_src(__file__)

# Ensure project root is importable so ``products.*`` imports resolve.
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from products.messaging.src.api import MessagingAPI  # noqa: E402
from products.messaging.src.storage import MessageStorage  # noqa: E402


@pytest_asyncio.fixture
async def storage(tmp_path):
    """Provide a connected MessageStorage backed by a temporary SQLite database."""
    dsn = f"sqlite:///{tmp_path}/messaging_test.db"
    s = MessageStorage(dsn=dsn)
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def api(storage):
    """Provide a MessagingAPI instance backed by temporary storage."""
    return MessagingAPI(storage=storage)
