"""T-3 sandbox parity: /v1/health p50 SLO (P0-7).

The v1.2.4 audit flagged p50 = 5.2s on the live sandbox — 17x
worse than v1.2.3. This test burns 50 sequential health requests
and asserts p50 < 1000ms. We deliberately pick a conservative
threshold here (vs. the 50ms target used in the in-process SLO
test in ``gateway/tests/perf/``) because the sandbox path goes
through Cloudflare / nginx / gunicorn / gateway / SQLite, which
adds ~150ms of unavoidable network overhead from GitHub runners.

Regression criterion: if the p50 blows past 1s we have reopened
the class of bug P0-7 fixed. That's what this gate catches.
"""

from __future__ import annotations

import statistics
import time

import pytest

pytestmark = pytest.mark.asyncio


_N_REQUESTS = 50


class TestSandboxHealthSlo:
    async def test_health_p50_under_1s(self, sandbox_client):
        latencies_ms: list[float] = []
        for _ in range(_N_REQUESTS):
            t0 = time.perf_counter()
            resp = await sandbox_client.get("/v1/health")
            dt = (time.perf_counter() - t0) * 1000.0
            assert resp.status_code == 200, f"health failed: {resp.status_code}"
            latencies_ms.append(dt)

        latencies_ms.sort()
        p50 = statistics.median(latencies_ms)
        p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
        p99 = latencies_ms[min(len(latencies_ms) - 1, int(len(latencies_ms) * 0.99))]

        # Surface the numbers on every run so we can spot creeping regressions.
        print(f"\n[sandbox health SLO] p50={p50:.0f}ms p95={p95:.0f}ms p99={p99:.0f}ms")

        assert p50 < 1000.0, (
            f"sandbox /v1/health p50={p50:.0f}ms exceeds 1000ms SLO. "
            f"Distribution: p95={p95:.0f}ms p99={p99:.0f}ms. "
            f"Run perf/p50_profile.py against the sandbox to diagnose."
        )
