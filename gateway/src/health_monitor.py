import asyncio
import logging

import httpx

from marketplace_src.models import ServiceSearchParams

logger = logging.getLogger("a2a.health_monitor")


class HealthMonitor:
    """Periodically probes registered marketplace services and publishes
    trust-score events when a service endpoint is unreachable or unhealthy."""

    def __init__(self, marketplace, event_bus, interval: int = 300, timeout: float = 10.0):
        self.marketplace = marketplace
        self.event_bus = event_bus
        self.interval = interval
        self.timeout = timeout

    async def check_services(self) -> None:
        """One-shot health check of all active services that expose an endpoint."""
        services = await self.marketplace.search(ServiceSearchParams(limit=1000))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for service in services:
                endpoint = getattr(service, "endpoint", None)
                if not endpoint:
                    continue

                try:
                    response = await client.get(endpoint)
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error {response.status_code}",
                            request=response.request,
                            response=response,
                        )
                    logger.info(
                        "Health check passed for service %s (provider %s): %d",
                        service.id,
                        service.provider_id,
                        response.status_code,
                    )
                except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                    logger.warning(
                        "Health check FAILED for service %s (provider %s): %s",
                        service.id,
                        service.provider_id,
                        exc,
                    )
                    await self.event_bus.publish(
                        "trust.score_updated",
                        source="health_monitor",
                        payload={
                            "server_id": service.provider_id,
                            "composite_score": 0,
                        },
                    )

    async def run(self) -> None:
        """Polling loop — calls check_services() every *interval* seconds.

        Catches all exceptions so the monitor never silently dies."""
        while True:
            try:
                await self.check_services()
            except Exception:  # Intentionally broad — monitor must never die
                logger.exception("Unexpected error during health check cycle")
            await asyncio.sleep(self.interval)
