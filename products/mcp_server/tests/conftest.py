"""Test configuration for a2a-mcp-server."""

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
