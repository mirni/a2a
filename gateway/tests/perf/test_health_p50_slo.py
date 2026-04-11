"""v1.2.4 audit P0-7: `/v1/health` latency SLO regression gate.

The external audit measured p50=5.2s on the sandbox, a ~25×
regression vs. the ~200ms expected. Because the audit probes a
remote deploy it mixes in Cloudflare + DNS + cold-start, so we
can't reproduce that exact number locally. What we *can* do is
pin a tight local SLO against the in-process ASGI client so any
future refactor that re-runs lifespan code per request, or
introduces a sync lock on the hot path, fails CI on the way out.

The test is marked ``@pytest.mark.slo`` so it can be excluded
from fast-developer iterations by ``-m "not slo"``. It runs by
default in CI.

Thresholds
----------

* ``p50 < 50ms`` — in-process ASGI has no network, no real TLS,
  no DNS. Anything slower than 50ms for an unauthenticated
  health check means someone added a per-request DB hit,
  loaded a new import at call time, or otherwise put work on
  the hot path.
* ``p99 < 250ms`` — allows for the first-call warmup and any
  single unlucky GC pause.

If this regresses, the fix is almost always to move work into
the app lifespan (see the ``suspect list`` in the audit plan).

Sandbox SLO (separate job, ``tests/sandbox/test_health_latency``)
asserts the tighter ``p50 < 300ms`` target against the real
deploy once the local gate passes.
"""

from __future__ import annotations

import time

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.slo]


class TestHealthP50Slo:
    async def test_p50_under_50ms_p99_under_250ms(self, client):
        """200 sequential calls: p50 < 50ms, p99 < 250ms.

        Runs against the in-process ASGI transport, so latency
        is effectively pure Python dispatch + the health
        handler's own work.
        """
        samples: list[float] = []
        # Warm-up: first call pays any one-time import/prime cost.
        warmup = await client.get("/v1/health")
        assert warmup.status_code == 200

        for _ in range(200):
            t0 = time.perf_counter()
            resp = await client.get("/v1/health")
            dt = (time.perf_counter() - t0) * 1000.0  # ms
            assert resp.status_code == 200
            samples.append(dt)

        samples.sort()
        p50 = samples[len(samples) // 2]
        p99 = samples[int(len(samples) * 0.99)]
        p_max = samples[-1]

        # Local ASGI is an order of magnitude faster than the
        # sandbox, so the gate is correspondingly tighter.
        assert p50 < 50.0, (
            f"health p50 regressed: {p50:.1f}ms (limit 50ms). "
            f"p99={p99:.1f}ms max={p_max:.1f}ms. "
            f"Something is doing per-request work on /v1/health."
        )
        assert p99 < 250.0, (
            f"health p99 regressed: {p99:.1f}ms (limit 250ms). "
            f"p50={p50:.1f}ms max={p_max:.1f}ms."
        )
