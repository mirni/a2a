"""Minimal anomaly detection: per-agent auth failure and rate-limit tracking.

Emits WARNING logs when thresholds are exceeded. Full alerting (webhook,
PagerDuty, etc.) is a follow-up task.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger("a2a.anomaly")

# Thresholds
_AUTH_FAILURE_THRESHOLD = 5  # per agent per window
_AUTH_FAILURE_WINDOW = 60  # seconds
_RATE_LIMIT_THRESHOLD = 10  # per agent per window
_RATE_LIMIT_WINDOW = 300  # seconds


class AnomalyDetector:
    """Tracks per-agent auth failures and rate-limit hits in memory."""

    def __init__(self) -> None:
        self._auth_failures: dict[str, list[float]] = defaultdict(list)
        self._rate_limit_hits: dict[str, list[float]] = defaultdict(list)

    def record_auth_failure(self, agent_id: str) -> None:
        """Record an authentication failure for an agent."""
        now = time.monotonic()
        events = self._auth_failures[agent_id]
        events.append(now)
        # Prune old events
        cutoff = now - _AUTH_FAILURE_WINDOW
        self._auth_failures[agent_id] = [t for t in events if t > cutoff]

        if len(self._auth_failures[agent_id]) >= _AUTH_FAILURE_THRESHOLD:
            logger.warning(
                "ANOMALY: agent '%s' has %d auth failures in the last %ds",
                agent_id,
                len(self._auth_failures[agent_id]),
                _AUTH_FAILURE_WINDOW,
            )

    def record_rate_limit_hit(self, agent_id: str) -> None:
        """Record a rate-limit hit for an agent."""
        now = time.monotonic()
        events = self._rate_limit_hits[agent_id]
        events.append(now)
        cutoff = now - _RATE_LIMIT_WINDOW
        self._rate_limit_hits[agent_id] = [t for t in events if t > cutoff]

        if len(self._rate_limit_hits[agent_id]) >= _RATE_LIMIT_THRESHOLD:
            logger.warning(
                "ANOMALY: agent '%s' has %d rate-limit hits in the last %ds",
                agent_id,
                len(self._rate_limit_hits[agent_id]),
                _RATE_LIMIT_WINDOW,
            )


# Singleton instance
detector = AnomalyDetector()
