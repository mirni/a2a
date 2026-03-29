"""Shared fixtures for payment tests.

Handles the import namespace collision between billing's src/ and payments' src/
by using sys.path manipulation and a virtual 'payments' package.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types

# ---------------------------------------------------------------------------
# Fix sys.path: ensure billing's src is found before payments' src.
# pytest inserts the conftest's parent directories into sys.path[0], which
# causes products/payments/src to shadow products/billing/src.
# ---------------------------------------------------------------------------
_billing_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "billing"))
_payments_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Remove any existing references to payments root that might shadow billing
sys.path = [p for p in sys.path if os.path.abspath(p) != _payments_root]

# Ensure billing is at the front
if _billing_root not in sys.path:
    sys.path.insert(0, _billing_root)

# ---------------------------------------------------------------------------
# Register shared_src so cross-product imports (db_security) resolve
# ---------------------------------------------------------------------------
_shared_src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src"))
if "shared_src" not in sys.modules:
    _shared_pkg = types.ModuleType("shared_src")
    _shared_pkg.__path__ = [_shared_src_dir]
    _shared_pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _shared_pkg

# ---------------------------------------------------------------------------
# Register 'payments' as a virtual package pointing to payments/src/
# ---------------------------------------------------------------------------
_payments_src = os.path.join(_payments_root, "src")

if "payments" not in sys.modules:
    _pkg = types.ModuleType("payments")
    _pkg.__path__ = [_payments_src]
    _pkg.__package__ = "payments"
    sys.modules["payments"] = _pkg

# ---------------------------------------------------------------------------
# Now imports work correctly:
# - 'src.xxx' resolves to billing
# - 'payments.xxx' resolves to payments
# ---------------------------------------------------------------------------
import pytest
from payments.engine import PaymentEngine
from payments.scheduler import SubscriptionScheduler
from payments.storage import PaymentStorage
from src.storage import StorageBackend as BillingStorageBackend
from src.wallet import Wallet as BillingWallet

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def billing_db():
    """Yield a temporary database path for billing, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".billing.db")
    os.close(fd)
    yield f"sqlite:///{path}"
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
async def payment_db():
    """Yield a temporary database path for payments, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".payment.db")
    os.close(fd)
    yield f"sqlite:///{path}"
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@pytest.fixture
async def billing_storage(billing_db):
    """Yield a connected billing StorageBackend, closed after test."""
    backend = BillingStorageBackend(dsn=billing_db)
    await backend.connect()
    yield backend
    await backend.close()


@pytest.fixture
async def billing_wallet(billing_storage):
    """Yield a billing Wallet instance backed by test storage."""
    return BillingWallet(storage=billing_storage)


@pytest.fixture
async def payment_storage(payment_db):
    """Yield a connected PaymentStorage, closed after test."""
    storage = PaymentStorage(dsn=payment_db)
    await storage.connect()
    yield storage
    await storage.close()


@pytest.fixture
async def engine(payment_storage, billing_wallet):
    """Yield a PaymentEngine wired to test storage and wallet."""
    return PaymentEngine(storage=payment_storage, wallet=billing_wallet)


@pytest.fixture
async def scheduler(engine):
    """Yield a SubscriptionScheduler backed by the test engine."""
    return SubscriptionScheduler(engine=engine)


@pytest.fixture
async def funded_wallets(billing_wallet):
    """Create two funded agent wallets for testing.

    Returns (wallet, payer_id, payee_id).
    - agent-a: 1000.0 credits
    - agent-b: 500.0 credits
    """
    await billing_wallet.create("agent-a", initial_balance=1000.0)
    await billing_wallet.create("agent-b", initial_balance=500.0)
    return billing_wallet, "agent-a", "agent-b"
