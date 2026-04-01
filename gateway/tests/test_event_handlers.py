"""Tests for gateway.src.event_handlers — cross-product event wiring."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from shared_src.event_bus import EventBus

from gateway.src.event_handlers import (
    make_billing_webhook_handler,
    make_marketplace_suspend_handler,
    make_trust_drop_handler,
    register_all_handlers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(payload: dict, event_type: str = "test", event_id: str = "ev-1") -> dict:
    return {"id": event_id, "event_type": event_type, "source": "test", "payload": payload}


def _make_service(service_id: str, status: str = "active"):
    svc = MagicMock()
    svc.id = service_id
    svc.status.value = status
    return svc


# ---------------------------------------------------------------------------
# trust_drop_handler
# ---------------------------------------------------------------------------


class TestTrustDropHandler:
    @pytest.mark.asyncio
    async def test_publishes_when_below_threshold(self):
        bus = AsyncMock(spec=EventBus)
        handler = make_trust_drop_handler(bus, threshold=50.0)
        event = _make_event({"server_id": "srv-1", "composite_score": 30.0})

        await handler(event)

        bus.publish.assert_awaited_once()
        args = bus.publish.call_args
        assert args[0][0] == "trust.score_drop"
        assert args[0][2]["composite_score"] == 30.0

    @pytest.mark.asyncio
    async def test_ignores_score_above_threshold(self):
        bus = AsyncMock(spec=EventBus)
        handler = make_trust_drop_handler(bus, threshold=50.0)
        event = _make_event({"server_id": "srv-1", "composite_score": 75.0})

        await handler(event)

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_score_equal_to_threshold_no_publish(self):
        bus = AsyncMock(spec=EventBus)
        handler = make_trust_drop_handler(bus, threshold=50.0)
        event = _make_event({"server_id": "srv-1", "composite_score": 50.0})

        await handler(event)

        bus.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_composite_score_defaults_to_100(self):
        bus = AsyncMock(spec=EventBus)
        handler = make_trust_drop_handler(bus, threshold=50.0)
        event = _make_event({"server_id": "srv-1"})  # no composite_score

        await handler(event)

        bus.publish.assert_not_awaited()  # 100 >= 50


# ---------------------------------------------------------------------------
# marketplace_suspend_handler
# ---------------------------------------------------------------------------


class TestMarketplaceSuspendHandler:
    @pytest.mark.asyncio
    async def test_deactivates_active_services(self):
        marketplace = AsyncMock()
        marketplace.get_provider_services.return_value = [
            _make_service("svc-1", "active"),
            _make_service("svc-2", "active"),
        ]
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({"server_id": "srv-1"})

        await handler(event)

        assert marketplace.deactivate_service.await_count == 2

    @pytest.mark.asyncio
    async def test_skips_inactive_services(self):
        marketplace = AsyncMock()
        marketplace.get_provider_services.return_value = [
            _make_service("svc-1", "inactive"),
        ]
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({"server_id": "srv-1"})

        await handler(event)

        marketplace.deactivate_service.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_services_no_error(self):
        marketplace = AsyncMock()
        marketplace.get_provider_services.return_value = []
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({"server_id": "srv-1"})

        await handler(event)

        marketplace.deactivate_service.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_server_id_returns_early(self):
        marketplace = AsyncMock()
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({})  # no server_id

        await handler(event)

        marketplace.get_provider_services.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_runtime_error_logged(self, caplog):
        marketplace = AsyncMock()
        marketplace.get_provider_services.side_effect = RuntimeError("db gone")
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({"server_id": "srv-1"})

        with caplog.at_level(logging.ERROR, logger="a2a.events"):
            await handler(event)

        assert "Failed to suspend services" in caplog.text

    @pytest.mark.asyncio
    async def test_lookup_error_logged(self, caplog):
        marketplace = AsyncMock()
        marketplace.get_provider_services.side_effect = LookupError("not found")
        handler = make_marketplace_suspend_handler(marketplace)
        event = _make_event({"server_id": "srv-1"})

        with caplog.at_level(logging.ERROR, logger="a2a.events"):
            await handler(event)

        assert "Failed to suspend services" in caplog.text


# ---------------------------------------------------------------------------
# billing_webhook_handler
# ---------------------------------------------------------------------------


class TestBillingWebhookHandler:
    @pytest.mark.asyncio
    async def test_calls_deliver_when_manager_present(self):
        wm = AsyncMock()
        handler = make_billing_webhook_handler(wm)
        event = _make_event({"amount": 10}, event_type="billing.deposit")

        await handler(event)

        wm.deliver.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_no_manager_still_succeeds(self):
        handler = make_billing_webhook_handler(None)
        event = _make_event({"amount": 10}, event_type="billing.deposit")

        await handler(event)  # should not raise

    @pytest.mark.asyncio
    async def test_runtime_error_logged(self, caplog):
        wm = AsyncMock()
        wm.deliver.side_effect = RuntimeError("delivery failed")
        handler = make_billing_webhook_handler(wm)
        event = _make_event({"amount": 10}, event_type="billing.deposit", event_id="ev-99")

        with caplog.at_level(logging.ERROR, logger="a2a.events"):
            await handler(event)

        assert "Failed to deliver webhook" in caplog.text


# ---------------------------------------------------------------------------
# register_all_handlers
# ---------------------------------------------------------------------------


class TestRegisterAllHandlers:
    @pytest.mark.asyncio
    async def test_returns_subscription_ids(self, tmp_path):
        dsn = f"sqlite:///{tmp_path}/events.db"
        bus = EventBus(dsn)
        await bus.connect()
        marketplace = AsyncMock()

        sub_ids = await register_all_handlers(bus, marketplace)

        assert len(sub_ids) == 5  # trust_drop, marketplace_suspend, payment_settlement, 2x billing_webhook
        assert all(isinstance(sid, str) for sid in sub_ids)
        await bus.close()

    @pytest.mark.asyncio
    async def test_payment_settlement_publishes_audit(self, tmp_path):
        dsn = f"sqlite:///{tmp_path}/events.db"
        bus = EventBus(dsn)
        await bus.connect()
        marketplace = AsyncMock()
        await register_all_handlers(bus, marketplace)

        received = []

        async def capture(event):
            received.append(event)

        await bus.subscribe("audit.payment_settled", capture)

        await bus.publish("payment.settled", "payments", {"intent_id": "pi-1"})
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0]["payload"]["original_event_id"] is not None
        await bus.close()
