"""Cross-product event handlers for the A2A event bus.

Wires together trust, marketplace, payments, and billing products so that
events in one product trigger reactions in others:

- Trust score drops  -> marketplace service deactivation
- Payment settlements -> audit logging
- Billing events     -> webhook dispatch logging
"""

from __future__ import annotations

import logging
from typing import Any

from shared_src.event_bus import EventBus

logger = logging.getLogger("a2a.events")


# ---------------------------------------------------------------------------
# Handler: trust score drop -> publish trust.score_drop event
# ---------------------------------------------------------------------------

def make_trust_drop_handler(event_bus: EventBus, threshold: float = 50.0):
    """Create a handler that publishes ``trust.score_drop`` when a score
    falls below *threshold*.

    Subscribe this to ``trust.score_updated`` events whose payloads include
    ``{"server_id": ..., "composite_score": ...}``.
    """

    async def trust_drop_handler(event: dict[str, Any]) -> None:
        score = event["payload"].get("composite_score", 100)
        server_id = event["payload"].get("server_id", "unknown")
        if score < threshold:
            await event_bus.publish(
                "trust.score_drop",
                "trust",
                {
                    "server_id": server_id,
                    "composite_score": score,
                    "threshold": threshold,
                },
            )
            logger.warning(
                "trust.score_drop published for server %s (score=%.1f)",
                server_id,
                score,
            )

    return trust_drop_handler


# ---------------------------------------------------------------------------
# Handler: trust.score_drop -> deactivate marketplace services
# ---------------------------------------------------------------------------

def make_marketplace_suspend_handler(marketplace: Any):
    """Create a handler that deactivates marketplace services when a
    ``trust.score_drop`` event fires.

    Args:
        marketplace: Marketplace instance with ``get_provider_services``
                     and ``deactivate_service`` methods.
    """

    async def marketplace_suspend_handler(event: dict[str, Any]) -> None:
        server_id = event["payload"].get("server_id")
        if not server_id:
            return

        try:
            services = await marketplace.get_provider_services(server_id)
            for svc in services:
                if svc.status.value == "active":
                    await marketplace.deactivate_service(svc.id)
                    logger.info(
                        "Deactivated service %s for provider %s due to trust drop",
                        svc.id,
                        server_id,
                    )
        except Exception:
            logger.exception(
                "Failed to suspend services for provider %s", server_id
            )

    return marketplace_suspend_handler


# ---------------------------------------------------------------------------
# Handler: payment.settled -> publish audit event
# ---------------------------------------------------------------------------

def make_payment_settlement_handler(event_bus: EventBus):
    """Create a handler that publishes an ``audit.payment_settled`` event
    when a ``payment.settled`` event is received."""

    async def payment_settlement_handler(event: dict[str, Any]) -> None:
        await event_bus.publish(
            "audit.payment_settled",
            "payments",
            {
                "original_event_id": event["id"],
                "payload": event["payload"],
            },
        )
        logger.info("Audit event published for payment settlement %s", event["id"])

    return payment_settlement_handler


# ---------------------------------------------------------------------------
# Handler: billing.* -> log for webhook dispatch
# ---------------------------------------------------------------------------

def make_billing_webhook_handler():
    """Create a handler that logs billing events for future webhook dispatch.

    Subscribes to ``billing.*`` events and logs them so they can be
    forwarded to external webhook endpoints later.
    """

    async def billing_webhook_handler(event: dict[str, Any]) -> None:
        logger.info(
            "Billing webhook queued: type=%s source=%s payload=%s",
            event["event_type"],
            event["source"],
            event["payload"],
        )

    return billing_webhook_handler


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

async def register_all_handlers(
    event_bus: EventBus,
    marketplace: Any,
    trust_threshold: float = 50.0,
) -> list[str]:
    """Register all cross-product event handlers and return subscription IDs.

    Args:
        event_bus: The shared EventBus instance.
        marketplace: The Marketplace instance.
        trust_threshold: Score below which services get suspended.

    Returns:
        List of subscription IDs for cleanup.
    """
    sub_ids: list[str] = []

    # trust.score_updated -> possibly publish trust.score_drop
    sub_ids.append(
        await event_bus.subscribe(
            "trust.score_updated",
            make_trust_drop_handler(event_bus, threshold=trust_threshold),
        )
    )

    # trust.score_drop -> deactivate marketplace services
    sub_ids.append(
        await event_bus.subscribe(
            "trust.score_drop",
            make_marketplace_suspend_handler(marketplace),
        )
    )

    # payment.settled -> audit event
    sub_ids.append(
        await event_bus.subscribe(
            "payment.settled",
            make_payment_settlement_handler(event_bus),
        )
    )

    # billing.usage_recorded -> webhook log
    sub_ids.append(
        await event_bus.subscribe(
            "billing.usage_recorded",
            make_billing_webhook_handler(),
        )
    )

    # billing.deposit -> webhook log
    sub_ids.append(
        await event_bus.subscribe(
            "billing.deposit",
            make_billing_webhook_handler(),
        )
    )

    logger.info("Registered %d cross-product event handlers", len(sub_ids))
    return sub_ids
