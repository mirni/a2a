"""Starlette lifespan: connect all storage backends on startup, close on shutdown."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator

from starlette.applications import Starlette

# Bootstrap cross-product imports (must happen before importing product modules)
import gateway.src.bootstrap  # noqa: F401

# Billing
from billing_src.tracker import UsageTracker

# Paywall
from paywall_src.keys import KeyManager
from paywall_src.storage import PaywallStorage

# Payments
from payments_src.engine import PaymentEngine
from payments_src.storage import PaymentStorage

# Marketplace
from marketplace_src.marketplace import Marketplace
from marketplace_src.storage import MarketplaceStorage

# Trust
from trust_src.api import TrustAPI
from trust_src.scorer import ScoreEngine
from trust_src.storage import StorageBackend as TrustStorage


@dataclass
class AppContext:
    """Holds all initialized product instances."""

    tracker: UsageTracker
    key_manager: KeyManager
    paywall_storage: PaywallStorage
    payment_engine: PaymentEngine
    marketplace: Marketplace
    trust_api: TrustAPI


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    """Initialize all backends on startup, tear down on shutdown."""

    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    os.makedirs(data_dir, exist_ok=True)

    billing_dsn = os.environ.get("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    paywall_dsn = os.environ.get("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    payments_dsn = os.environ.get("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    marketplace_dsn = os.environ.get(
        "MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db"
    )
    trust_dsn = os.environ.get("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")

    # --- Billing ---
    tracker = UsageTracker(billing_dsn)
    await tracker.connect()

    # --- Paywall ---
    paywall_storage = PaywallStorage(paywall_dsn)
    await paywall_storage.connect()
    key_manager = KeyManager(paywall_storage)

    # --- Payments ---
    payment_storage = PaymentStorage(payments_dsn)
    await payment_storage.connect()
    payment_engine = PaymentEngine(storage=payment_storage, wallet=tracker.wallet)

    # --- Trust --- (must init before marketplace so we can wire the adapter)
    trust_storage = TrustStorage(trust_dsn)
    await trust_storage.connect()
    scorer = ScoreEngine(storage=trust_storage)
    trust_api = TrustAPI(storage=trust_storage, scorer=scorer)

    # --- Marketplace ---
    from gateway.src.trust_adapter import make_trust_provider

    marketplace_storage = MarketplaceStorage(marketplace_dsn)
    await marketplace_storage.connect()
    trust_provider = make_trust_provider(trust_api)
    marketplace = Marketplace(storage=marketplace_storage, trust_provider=trust_provider)

    # Store on app.state
    app.state.ctx = AppContext(
        tracker=tracker,
        key_manager=key_manager,
        paywall_storage=paywall_storage,
        payment_engine=payment_engine,
        marketplace=marketplace,
        trust_api=trust_api,
    )

    yield

    # --- Shutdown ---
    await trust_storage.close()
    await marketplace_storage.close()
    await payment_storage.close()
    await paywall_storage.close()
    await tracker.close()
