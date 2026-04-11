"""v1.2.4 audit P0-7: `/v1/health` latency triage profiler.

Run sequential GET /v1/health against any deployment and report
p50/p95/p99 latency plus cold vs. warm split. Used to identify
the hot-path regression the audit flagged (p50 5.2s on sandbox).

Usage::

    python perf/p50_profile.py http://localhost:8080 500

    python perf/p50_profile.py https://sandbox.greenhelix.net 500

Exits 0 always; this is diagnostic only. The CI SLO gate lives
in ``gateway/tests/perf/test_health_p50_slo.py`` and
``tests/sandbox/test_health_latency.py``.
"""

from __future__ import annotations

import statistics
import sys
import time
from typing import Any

try:
    import httpx
except ImportError:
    print("httpx is required: pip install httpx", file=sys.stderr)
    sys.exit(0)


def main(base_url: str, n: int) -> None:
    url = base_url.rstrip("/") + "/v1/health"
    print(f"Profiling {n} sequential GETs to {url}")

    samples_ms: list[float] = []
    errors = 0

    with httpx.Client(timeout=30.0) as client:
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                r = client.get(url)
                if r.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1
                continue
            samples_ms.append((time.perf_counter() - t0) * 1000.0)

    if not samples_ms:
        print("No samples collected.")
        return

    samples_ms.sort()
    cold = samples_ms[0]
    warm_median = statistics.median(samples_ms[5:]) if len(samples_ms) > 5 else statistics.median(samples_ms)

    def _p(pct: float) -> float:
        idx = min(len(samples_ms) - 1, int(len(samples_ms) * pct))
        return samples_ms[idx]

    print()
    print(f"  n          = {len(samples_ms)}")
    print(f"  errors     = {errors}")
    print(f"  cold       = {cold:.1f} ms  (first request)")
    print(f"  warm med.  = {warm_median:.1f} ms  (after 5-request warmup)")
    print(f"  p50        = {_p(0.50):.1f} ms")
    print(f"  p95        = {_p(0.95):.1f} ms")
    print(f"  p99        = {_p(0.99):.1f} ms")
    print(f"  max        = {samples_ms[-1]:.1f} ms")


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    main(base, count)
