"""Shared fixtures for messaging product tests."""

from __future__ import annotations

import os
import sys

import pytest
import pytest_asyncio

# Ensure project root is importable
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for p in [_project_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from products.messaging.src.api import MessagingAPI
from products.messaging.src.storage import MessageStorage


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
