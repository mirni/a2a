"""Test configuration for a2a-mcp-server.

Ensures the package src/ directory is importable regardless of how the
tests are launched (pytest from repo root, scripts/run_tests.sh, CI).
"""

from __future__ import annotations

import os
import sys

import pytest

_src = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _src not in sys.path:
    sys.path.insert(0, _src)


@pytest.fixture
def anyio_backend():
    return "asyncio"
