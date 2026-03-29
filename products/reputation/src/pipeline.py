"""ReputationPipeline: orchestrates continuous monitoring of registered targets.

Manages probe targets, runs probe and scan cycles at configurable intervals,
and triggers score recomputation after each cycle.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .aggregator import Aggregator
from .models import PipelineConfig, ProbeTarget
from .probe_worker import ProbeWorker
from .scan_worker import ScanWorker
from .storage import ReputationStorage

try:
    from src.models import Server, TransportType
except ImportError:
    from products.trust.src.models import Server, TransportType

logger = logging.getLogger(__name__)


@dataclass
class ReputationPipeline:
    """Orchestrates the reputation data collection pipeline.

    Manages the full lifecycle: registering targets, running probe and scan
    cycles, and triggering score aggregation.

    Attributes:
        trust_storage: Trust module StorageBackend for probes/scans/scores.
        reputation_storage: Reputation module storage for probe targets.
        probe_worker: Worker that executes HTTP health probes.
        scan_worker: Worker that executes security scans.
        aggregator: Aggregator that recomputes trust scores.
        config: Pipeline configuration.
    """

    trust_storage: object
    reputation_storage: ReputationStorage
    probe_worker: ProbeWorker
    scan_worker: ScanWorker
    aggregator: Aggregator
    config: PipelineConfig = field(default_factory=PipelineConfig)
    _running: bool = field(default=False, init=False, repr=False)
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)

    async def add_target(
        self,
        url: str,
        server_id: str,
        probe_interval: float | None = None,
        scan_interval: float | None = None,
    ) -> ProbeTarget:
        """Register a new target for continuous monitoring.

        Also registers the server in trust storage if not already present.

        Args:
            url: The URL to monitor.
            server_id: Unique identifier for the server.
            probe_interval: Override default probe interval (seconds).
            scan_interval: Override default scan interval (seconds).

        Returns:
            The created ProbeTarget.
        """
        target = ProbeTarget(
            server_id=server_id,
            url=url,
            probe_interval=probe_interval or self.config.probe_schedule.interval_seconds,
            scan_interval=scan_interval or self.config.scan_schedule.interval_seconds,
        )
        await self.reputation_storage.add_target(target)

        # Ensure server exists in trust storage
        existing = await self.trust_storage.get_server(server_id)
        if existing is None:
            server = Server(
                id=server_id,
                name=server_id,
                url=url,
                transport_type=TransportType.HTTP,
                registered_at=time.time(),
            )
            await self.trust_storage.register_server(server)

        logger.info("Added target: %s (%s)", server_id, url)
        return target

    async def remove_target(self, server_id: str) -> bool:
        """Remove a target from monitoring.

        Args:
            server_id: The server to remove.

        Returns:
            True if the target was found and removed.
        """
        removed = await self.reputation_storage.remove_target(server_id)
        if removed:
            logger.info("Removed target: %s", server_id)
        return removed

    async def run_once(self, now: float | None = None) -> dict:
        """Run a single pipeline cycle: probe, scan, aggregate.

        Probes all targets due for probing, scans those due for scanning,
        then recomputes trust scores for all probed/scanned servers.

        Args:
            now: Current time override (for testing).

        Returns:
            Dict with counts: probed, scanned, scored.
        """
        if now is None:
            now = time.time()

        # Get targets due for probe
        probe_targets = await self.reputation_storage.get_due_for_probe(now)
        probed_ids = set()

        # Execute probes
        for target in probe_targets:
            try:
                await self.probe_worker.probe(target.server_id, target.url)
                await self.reputation_storage.update_last_probed(target.server_id, now)
                probed_ids.add(target.server_id)
            except Exception as exc:
                logger.error("Probe failed for %s: %s", target.server_id, exc)

        # Get targets due for scan
        scan_targets = await self.reputation_storage.get_due_for_scan(now)
        scanned_ids = set()

        # Execute scans
        for target in scan_targets:
            try:
                await self.scan_worker.scan(target.server_id, target.url)
                await self.reputation_storage.update_last_scanned(target.server_id, now)
                scanned_ids.add(target.server_id)
            except Exception as exc:
                logger.error("Scan failed for %s: %s", target.server_id, exc)

        # Recompute scores for all servers that were probed or scanned
        scored_ids = probed_ids | scanned_ids
        if scored_ids:
            await self.aggregator.recompute_scores(list(scored_ids), now=now)

        result = {
            "probed": len(probed_ids),
            "scanned": len(scanned_ids),
            "scored": len(scored_ids),
        }
        logger.debug("Pipeline cycle: %s", result)
        return result

    async def recompute_scores(self, server_id: str | None = None, now: float | None = None):
        """Manually trigger score recomputation.

        Args:
            server_id: Specific server to recompute, or None for all active targets.
            now: Current time override.

        Returns:
            List of computed TrustScore objects.
        """
        if server_id is not None:
            return [await self.aggregator.recompute_score(server_id, now=now)]
        return await self.aggregator.recompute_all_active(self.reputation_storage, now=now)

    async def start(self) -> None:
        """Start the continuous monitoring loop.

        Runs pipeline cycles at the configured cycle_interval until stop() is called.
        """
        if self._running:
            logger.warning("Pipeline already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Pipeline started (cycle_interval=%.1fs)", self.config.cycle_interval)

    async def stop(self) -> None:
        """Stop the continuous monitoring loop gracefully."""
        if not self._running:
            return

        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Pipeline stopped")

    @property
    def is_running(self) -> bool:
        """Whether the pipeline loop is currently running."""
        return self._running

    async def _run_loop(self) -> None:
        """Internal loop that runs pipeline cycles."""
        try:
            while self._running:
                try:
                    await self.run_once()
                except Exception as exc:
                    logger.error("Pipeline cycle error: %s", exc)
                await asyncio.sleep(self.config.cycle_interval)
        except asyncio.CancelledError:
            pass

    async def get_target(self, server_id: str) -> ProbeTarget | None:
        """Get a registered target by server_id."""
        return await self.reputation_storage.get_target(server_id)

    async def list_targets(self, active_only: bool = True) -> list[ProbeTarget]:
        """List all registered targets."""
        return await self.reputation_storage.list_targets(active_only=active_only)
