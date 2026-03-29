"""Aggregator: recomputes trust scores from recent probe and scan data.

Calls the trust scoring engine's compute_trust_score function and stores
the resulting scores via the trust storage backend.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

# Import trust scorer and models
try:
    from src.models import Window
    from src.scorer import compute_trust_score
except ImportError:
    from products.trust.src.models import Window
    from products.trust.src.scorer import compute_trust_score

logger = logging.getLogger(__name__)

# Window durations in seconds (mirrors trust scorer)
WINDOW_SECONDS = {
    Window.H24: 86400,
    Window.D7: 604800,
    Window.D30: 30 * 86400,
}


@dataclass
class Aggregator:
    """Recomputes trust scores from stored probe and scan data.

    Reads recent probes and scans from trust storage, calls compute_trust_score,
    and stores the resulting TrustScore back to trust storage.

    Attributes:
        trust_storage: The trust StorageBackend for reading data and storing scores.
    """

    trust_storage: object  # StorageBackend from trust module

    async def recompute_score(
        self,
        server_id: str,
        window: Window = Window.H24,
        now: float | None = None,
    ) -> object:
        """Recompute the trust score for a single server.

        Args:
            server_id: The server to score.
            window: Time window for aggregation (default 24h).
            now: Current time override (for testing).

        Returns:
            The computed TrustScore object.
        """
        if now is None:
            now = time.time()

        window_seconds = WINDOW_SECONDS[window]
        since = now - window_seconds

        # Fetch probe results and security scans from trust storage
        probes = await self.trust_storage.get_probe_results(server_id, since=since)
        scans = await self.trust_storage.get_security_scans(server_id)

        # Compute score using trust scoring engine
        score = compute_trust_score(
            server_id=server_id,
            probes=probes,
            scans=scans,
            window=window,
            now=now,
        )

        # Store the computed score
        await self.trust_storage.store_trust_score(score)

        logger.debug(
            "Recomputed score for %s: composite=%.2f confidence=%.2f",
            server_id,
            score.composite_score,
            score.confidence,
        )

        return score

    async def recompute_scores(
        self,
        server_ids: list[str],
        window: Window = Window.H24,
        now: float | None = None,
    ) -> list[object]:
        """Recompute trust scores for multiple servers.

        Args:
            server_ids: List of server identifiers to score.
            window: Time window for aggregation.
            now: Current time override (for testing).

        Returns:
            List of computed TrustScore objects.
        """
        if now is None:
            now = time.time()

        scores = []
        for server_id in server_ids:
            score = await self.recompute_score(server_id, window=window, now=now)
            scores.append(score)
        return scores

    async def recompute_all_active(
        self,
        reputation_storage: object,
        window: Window = Window.H24,
        now: float | None = None,
    ) -> list[object]:
        """Recompute scores for all active targets.

        Args:
            reputation_storage: ReputationStorage to get active target list.
            window: Time window for aggregation.
            now: Current time override (for testing).

        Returns:
            List of computed TrustScore objects.
        """
        targets = await reputation_storage.list_targets(active_only=True)
        server_ids = [t.server_id for t in targets]
        return await self.recompute_scores(server_ids, window=window, now=now)
