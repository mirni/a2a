"""Starlette lifespan: connect all storage backends on startup, close on shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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

# Identity
from identity_src.api import IdentityAPI
from identity_src.storage import IdentityStorage

# Shared — Event Bus
from shared_src.event_bus import EventBus

# Cross-product event handlers
from gateway.src.event_handlers import register_all_handlers

# Webhook delivery
from gateway.src.webhooks import WebhookManager

# Health monitoring
from gateway.src.health_monitor import HealthMonitor

# Signing
from gateway.src.signing import SigningManager

# Observability
from gateway.src.middleware import setup_structured_logging

logger = logging.getLogger("a2a.lifespan")


@dataclass
class AppContext:
    """Holds all initialized product instances."""

    tracker: UsageTracker
    key_manager: KeyManager
    paywall_storage: PaywallStorage
    payment_engine: PaymentEngine
    marketplace: Marketplace
    trust_api: TrustAPI
    identity_api: IdentityAPI
    event_bus: EventBus
    webhook_manager: WebhookManager
    scheduler: object | None = None
    health_monitor: HealthMonitor | None = None
    signing_manager: SigningManager | None = None


@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
    """Initialize all backends on startup, tear down on shutdown."""

    # Setup structured logging
    setup_structured_logging()

    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    os.makedirs(data_dir, exist_ok=True)

    billing_dsn = os.environ.get("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    paywall_dsn = os.environ.get("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    payments_dsn = os.environ.get("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    marketplace_dsn = os.environ.get(
        "MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db"
    )
    trust_dsn = os.environ.get("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    identity_dsn = os.environ.get("IDENTITY_DSN", f"sqlite:///{data_dir}/identity.db")
    event_bus_dsn = os.environ.get(
        "EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db"
    )
    webhook_dsn = os.environ.get(
        "WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db"
    )

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

    # --- Identity ---
    identity_storage = IdentityStorage(identity_dsn)
    await identity_storage.connect()
    identity_api = IdentityAPI(storage=identity_storage)

    # --- Marketplace ---
    from gateway.src.trust_adapter import make_trust_provider

    marketplace_storage = MarketplaceStorage(marketplace_dsn)
    await marketplace_storage.connect()
    trust_provider = make_trust_provider(trust_api)
    marketplace = Marketplace(storage=marketplace_storage, trust_provider=trust_provider)

    # --- Event Bus ---
    event_bus = EventBus(dsn=event_bus_dsn)
    await event_bus.connect()
    await register_all_handlers(event_bus, marketplace)

    # --- Webhook Manager ---
    webhook_manager = WebhookManager(webhook_dsn)
    await webhook_manager.connect()

    # --- Subscription Scheduler ---
    scheduler = None
    scheduler_task = None
    try:
        from payments_src.scheduler import SubscriptionScheduler

        scheduler = SubscriptionScheduler(engine=payment_engine)
        scheduler_task = asyncio.create_task(scheduler.run(interval=300))
        logger.info("Subscription scheduler started (interval=300s)")
    except Exception:
        logger.warning("Failed to start subscription scheduler", exc_info=True)

    # --- Health Monitor ---
    health_monitor = HealthMonitor(
        marketplace=marketplace, event_bus=event_bus, interval=300, timeout=10.0
    )
    health_monitor_task = asyncio.create_task(health_monitor.run())
    logger.info("Health monitor started (interval=300s)")

    # --- Signing Manager ---
    signing_manager = SigningManager()

    # Store on app.state
    ctx = AppContext(
        tracker=tracker,
        key_manager=key_manager,
        paywall_storage=paywall_storage,
        payment_engine=payment_engine,
        marketplace=marketplace,
        trust_api=trust_api,
        identity_api=identity_api,
        event_bus=event_bus,
        webhook_manager=webhook_manager,
        scheduler=scheduler,
        health_monitor=health_monitor,
        signing_manager=signing_manager,
    )
    app.state.ctx = ctx
    app.state.signing_manager = signing_manager

    yield

    # --- Shutdown ---
    # Cancel background tasks
    health_monitor_task.cancel()
    try:
        await health_monitor_task
    except asyncio.CancelledError:
        pass

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

    await webhook_manager.close()
    await event_bus.close()
    await identity_storage.close()
    await trust_storage.close()
    await marketplace_storage.close()
    await payment_storage.close()
    await paywall_storage.close()
    await tracker.close()
