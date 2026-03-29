"""Shared fixtures for paywall tests."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types

import pytest

# Register shared_src so cross-product imports (db_security) resolve
_shared_src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src"))
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

# ---------------------------------------------------------------------------
# Bootstrap: import the billing layer without polluting the "src" namespace.
# Both packages use "src/" as their root, so we load billing's tracker
# module directly via importlib.util to avoid collision.
# ---------------------------------------------------------------------------

_BILLING_SRC = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "billing", "src"))


def _import_billing_module(name: str, filepath: str):
    """Import a single module from the billing src/ directory."""
    spec = importlib.util.spec_from_file_location(f"billing_{name}", filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"billing_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


# Load billing modules in dependency order using their internal relative imports.
# We need to temporarily add billing root to sys.path so relative imports work.
_billing_root = os.path.normpath(os.path.join(_BILLING_SRC, ".."))
sys.path.insert(0, _billing_root)

# Import billing's src package under an alias to avoid clash
import importlib

_billing_pkg = importlib.import_module("src")
# Stash it so subsequent paywall "import src" can replace it
_billing_src_module = _billing_pkg
# Remove it from sys.modules so paywall can claim "src"
for key in list(sys.modules.keys()):
    if key == "src" or key.startswith("src."):
        mod = sys.modules.pop(key)
        # Re-register under billing_ prefix
        sys.modules[f"billing_{key}"] = mod

# Remove billing root from sys.path
sys.path.remove(_billing_root)

# Now the billing UsageTracker is at billing_src.tracker
from billing_src.tracker import UsageTracker as BillingTracker  # noqa: E402

# Now import paywall modules (the normal src package)
from src.keys import KeyManager  # noqa: E402
from src.middleware import PaywallMiddleware  # noqa: E402
from src.storage import PaywallStorage  # noqa: E402
from src.usage_api import UsageAPI  # noqa: E402


@pytest.fixture
async def tmp_db():
    """Yield a temporary database path, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield f"sqlite:///{path}"
    os.unlink(path)


@pytest.fixture
async def billing_tmp_db():
    """Yield a separate temporary database path for the billing layer."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield f"sqlite:///{path}"
    os.unlink(path)


@pytest.fixture
async def paywall_storage(tmp_db):
    """Yield a connected PaywallStorage, closed after test."""
    storage = PaywallStorage(dsn=tmp_db)
    await storage.connect()
    yield storage
    await storage.close()


@pytest.fixture
async def key_manager(paywall_storage):
    """Yield a KeyManager backed by the test storage."""
    return KeyManager(storage=paywall_storage)


@pytest.fixture
async def tracker(billing_tmp_db):
    """Yield a connected billing UsageTracker, closed after test."""
    t = BillingTracker(storage=billing_tmp_db)
    await t.connect()
    yield t
    await t.close()


@pytest.fixture
async def middleware(tracker, paywall_storage, key_manager):
    """Yield a fully initialized PaywallMiddleware."""
    mw = PaywallMiddleware(
        tracker=tracker,
        connector="test_connector",
        paywall_storage=paywall_storage,
        key_manager=key_manager,
    )
    mw._initialized = True
    yield mw


@pytest.fixture
async def usage_api(tracker, key_manager, paywall_storage):
    """Yield a UsageAPI instance."""
    return UsageAPI(
        tracker=tracker,
        key_manager=key_manager,
        storage=paywall_storage,
    )
