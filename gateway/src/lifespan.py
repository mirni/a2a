"""FastAPI lifespan: connect all storage backends on startup, close on shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

# Bootstrap cross-product imports — MUST happen before any *_src imports
import gateway.src.bootstrap  # noqa: F401, E402, I001

from fastapi import FastAPI

# Billing
from billing_src.tracker import UsageTracker  # noqa: E402

# Identity
from identity_src.api import IdentityAPI  # noqa: E402
from identity_src.storage import IdentityStorage  # noqa: E402

# Marketplace
from marketplace_src.marketplace import Marketplace  # noqa: E402
from marketplace_src.storage import MarketplaceStorage  # noqa: E402

# Messaging
from messaging_src.api import MessagingAPI  # noqa: E402
from messaging_src.storage import MessageStorage  # noqa: E402

# Payments
from payments_src.engine import PaymentEngine  # noqa: E402
from payments_src.storage import PaymentStorage  # noqa: E402

# Paywall
from paywall_src.keys import KeyManager  # noqa: E402
from paywall_src.storage import PaywallStorage  # noqa: E402

# Shared — Event Bus
from shared_src.event_bus import EventBus  # noqa: E402

# Trust
from trust_src.api import TrustAPI  # noqa: E402
from trust_src.scorer import ScoreEngine  # noqa: E402
from trust_src.storage import StorageBackend as TrustStorage  # noqa: E402

# Disputes
from gateway.src.disputes import DisputeEngine

# Cross-product event handlers
from gateway.src.event_handlers import register_all_handlers

# Cleanup tasks
from gateway.src.cleanup_tasks import (
    AggregateRefreshTask,
    DataLifecycleTask,
    EventBusCleanup,
    NonceCleanup,
    RateEventsCleanup,
    StripeSessionCleanup,
)

# Health monitoring
from gateway.src.health_monitor import HealthMonitor

# Observability
from gateway.src.middleware import setup_structured_logging

# Public rate limiter
from gateway.src.rate_limit_headers import PublicRateLimiter

# Signing
from gateway.src.signing import SigningManager

# Webhook delivery
from gateway.src.webhooks import WebhookManager

logger = logging.getLogger("a2a.lifespan")


def _get_secret(name: str, default: str | None = None) -> str | None:
    """Read a secret from systemd credentials directory, falling back to env vars.

    When the service is configured with LoadCredential= directives, systemd
    makes credentials available at $CREDENTIALS_DIRECTORY/<name>.  This
    helper checks that path first and falls back to os.environ.
    """
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir:
        path = os.path.join(cred_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                return f.read().strip()
    return os.environ.get(name, default)


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
    messaging_api: MessagingAPI | None = None
    dispute_engine: DisputeEngine | None = None
    scheduler: object | None = None
    health_monitor: HealthMonitor | None = None
    signing_manager: SigningManager | None = None
    mcp_proxy: object | None = None
    x402_verifier: object | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize all backends on startup, tear down on shutdown."""

    # Setup structured logging
    setup_structured_logging()

    # Audit C1: refuse to boot if A2A_ENV disagrees with Stripe key prefix.
    # (e.g. sandbox with sk_live_* would cause real charges.)
    from gateway.src.stripe_env_check import assert_stripe_key_matches_env

    assert_stripe_key_matches_env(
        env=os.environ.get("A2A_ENV"),
        stripe_key=_get_secret("STRIPE_API_KEY", "") or "",
    )

    data_dir = os.environ.get("A2A_DATA_DIR", "/tmp/a2a_gateway")
    os.makedirs(data_dir, exist_ok=True)

    billing_dsn = os.environ.get("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    paywall_dsn = os.environ.get("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    payments_dsn = os.environ.get("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    marketplace_dsn = os.environ.get("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    trust_dsn = os.environ.get("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    identity_dsn = os.environ.get("IDENTITY_DSN", f"sqlite:///{data_dir}/identity.db")
    event_bus_dsn = os.environ.get("EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db")
    webhook_dsn = os.environ.get("WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db")

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

    # --- Messaging ---
    messaging_dsn = os.environ.get("MESSAGING_DSN", f"sqlite:///{data_dir}/messaging.db")
    messaging_storage = MessageStorage(messaging_dsn)
    await messaging_storage.connect()
    messaging_api = MessagingAPI(storage=messaging_storage)

    # --- Dispute Engine ---
    dispute_dsn = os.environ.get("DISPUTE_DSN", f"sqlite:///{data_dir}/disputes.db")
    dispute_engine = DisputeEngine(dsn=dispute_dsn, payment_engine=payment_engine)
    await dispute_engine.connect()

    # --- Webhook Manager ---
    webhook_manager = WebhookManager(webhook_dsn)
    await webhook_manager.connect()

    # --- Pre-create tool-managed tables ---
    from gateway.src.tools._schemas import (
        ensure_budget_caps_table,
        ensure_event_schemas_table,
        ensure_service_ratings_table,
        ensure_x402_nonces_table,
    )

    await ensure_budget_caps_table(tracker.storage.db)
    await ensure_service_ratings_table(marketplace_storage.db)
    await ensure_event_schemas_table(event_bus.db)
    await ensure_x402_nonces_table(tracker.storage.db)

    # --- Restrict SQLite DB file permissions (owner-only) ---
    import stat

    for dsn_val in [
        billing_dsn,
        paywall_dsn,
        payments_dsn,
        marketplace_dsn,
        trust_dsn,
        identity_dsn,
        event_bus_dsn,
        webhook_dsn,
        messaging_dsn,
        dispute_dsn,
    ]:
        if dsn_val.startswith("sqlite:///"):
            db_path = dsn_val.replace("sqlite:///", "")
            if os.path.isfile(db_path):
                try:
                    os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
                except OSError:
                    logger.debug("Could not set permissions on %s", db_path)

    # --- Admin audit log table ---
    from gateway.src.admin_audit import ensure_admin_audit_table

    await ensure_admin_audit_table(tracker.storage.db)

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
    health_monitor = HealthMonitor(marketplace=marketplace, event_bus=event_bus, interval=300, timeout=10.0)
    health_monitor_task = asyncio.create_task(health_monitor.run())
    logger.info("Health monitor started (interval=300s)")

    # --- Rate Events Cleanup ---
    rate_events_cleanup = RateEventsCleanup(paywall_storage=paywall_storage, interval=3600)
    rate_events_cleanup_task = asyncio.create_task(rate_events_cleanup.run())
    logger.info("Rate events cleanup started (interval=3600s)")

    # --- Event Bus Cleanup ---
    event_bus_cleanup = EventBusCleanup(event_bus=event_bus, interval=3600, older_than_seconds=86400)
    event_bus_cleanup_task = asyncio.create_task(event_bus_cleanup.run())
    logger.info("Event bus cleanup started (interval=3600s, retention=86400s)")

    # --- Nonce Cleanup ---
    nonce_cleanup = NonceCleanup(identity_storage=identity_storage, interval=3600, ttl_seconds=300)
    nonce_cleanup_task = asyncio.create_task(nonce_cleanup.run())
    logger.info("Nonce cleanup started (interval=3600s, ttl=300s)")

    # --- Aggregate Refresh ---
    aggregate_refresh = AggregateRefreshTask(identity_storage=identity_storage, interval=3600)
    aggregate_refresh_task = asyncio.create_task(aggregate_refresh.run())
    logger.info("Aggregate refresh started (interval=3600s)")

    # --- Data Lifecycle ---
    data_lifecycle = DataLifecycleTask(identity_storage=identity_storage, interval=86400)
    data_lifecycle_task = asyncio.create_task(data_lifecycle.run())
    logger.info("Data lifecycle started (interval=86400s)")

    # --- Stripe Session Cleanup ---
    stripe_session_cleanup = StripeSessionCleanup(billing_db=tracker.storage.db, interval=86400)
    stripe_session_cleanup_task = asyncio.create_task(stripe_session_cleanup.run())
    logger.info("Stripe session cleanup started (interval=86400s, retention=30d)")

    # --- Signing Manager ---
    signing_manager = SigningManager()

    # --- MCP Proxy (connector tools) ---
    mcp_proxy = None
    try:
        from gateway.src.mcp_proxy import MCPProxyManager
        from gateway.src.tools import register_mcp_tools

        mcp_proxy = MCPProxyManager()
        register_mcp_tools(mcp_proxy)
        logger.info("MCP connector proxy initialized (tools registered, lazy-start)")
    except Exception:
        logger.warning("MCP proxy not available", exc_info=True)

    # --- x402 Protocol ---
    from gateway.src.config import GatewayConfig
    from gateway.src.x402 import USDC_CONTRACTS, X402Verifier

    x402_verifier = None
    config = GatewayConfig.from_env()
    if config.x402_enabled and config.x402_merchant_address:
        networks = {
            n.strip(): USDC_CONTRACTS[n.strip()]
            for n in config.x402_supported_networks.split(",")
            if n.strip() in USDC_CONTRACTS
        }
        x402_verifier = X402Verifier(
            merchant_address=config.x402_merchant_address,
            facilitator_url=config.x402_facilitator_url,
            supported_networks=networks,
            nonce_db=tracker.storage.db,
        )
        logger.info("x402 payment protocol enabled (merchant=%s)", config.x402_merchant_address)

    # --- Catalog validation ---
    from gateway.src.catalog import validate_catalog
    from gateway.src.tools import TOOL_REGISTRY

    validate_catalog(TOOL_REGISTRY)

    # --- Public Rate Limiter ---
    public_rate_limiter = PublicRateLimiter(limit=1000, window_seconds=3600)
    app.state.public_rate_limiter = public_rate_limiter
    logger.info("Public rate limiter initialized (limit=1000/hr)")

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
        messaging_api=messaging_api,
        dispute_engine=dispute_engine,
        scheduler=scheduler,
        health_monitor=health_monitor,
        signing_manager=signing_manager,
        mcp_proxy=mcp_proxy,
        x402_verifier=x402_verifier,
    )
    app.state.ctx = ctx
    app.state.signing_manager = signing_manager

    yield

    # --- Shutdown ---
    if mcp_proxy:
        await mcp_proxy.close()

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

    rate_events_cleanup_task.cancel()
    try:
        await rate_events_cleanup_task
    except asyncio.CancelledError:
        pass

    event_bus_cleanup_task.cancel()
    try:
        await event_bus_cleanup_task
    except asyncio.CancelledError:
        pass

    nonce_cleanup_task.cancel()
    try:
        await nonce_cleanup_task
    except asyncio.CancelledError:
        pass

    aggregate_refresh_task.cancel()
    try:
        await aggregate_refresh_task
    except asyncio.CancelledError:
        pass

    data_lifecycle_task.cancel()
    try:
        await data_lifecycle_task
    except asyncio.CancelledError:
        pass

    stripe_session_cleanup_task.cancel()
    try:
        await stripe_session_cleanup_task
    except asyncio.CancelledError:
        pass

    await messaging_storage.close()
    await dispute_engine.close()
    await webhook_manager.close()
    await event_bus.close()
    await identity_storage.close()
    await trust_storage.close()
    await marketplace_storage.close()
    await payment_storage.close()
    await paywall_storage.close()
    await tracker.close()
