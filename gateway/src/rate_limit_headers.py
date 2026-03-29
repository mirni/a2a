"""Shared rate limit header helpers.

Provides header builders for both authenticated (per-tier) and
unauthenticated (public/default) endpoints.
"""

from __future__ import annotations

import math
import time

# Default public rate limit for unauthenticated endpoints (per hour)
_PUBLIC_RATE_LIMIT = 1000


def public_rate_limit_headers() -> dict[str, str]:
    """Build X-RateLimit-* headers for unauthenticated (public) endpoints.

    Uses a fixed public rate limit since there is no per-agent tracking.
    """
    window_seconds = 3600.0
    reset = max(1, math.ceil(window_seconds - (time.time() % window_seconds)))
    return {
        "X-RateLimit-Limit": str(_PUBLIC_RATE_LIMIT),
        "X-RateLimit-Remaining": str(_PUBLIC_RATE_LIMIT),
        "X-RateLimit-Reset": str(reset),
    }
