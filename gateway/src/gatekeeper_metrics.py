"""Prometheus metrics for gatekeeper (formal verification) operations.

Exposes per-``(tier, result)`` counters and histograms so operators can
build dashboards like "pro tier failure rate", "premium solver time p99",
and "total credits burned on verification per day".

This module is intentionally stand-alone (no ``prometheus_client``
dependency) — the gateway already ships its own tiny Prometheus text
exposer (see :class:`gateway.src.middleware.Metrics`). Using the same
style keeps the ``/v1/metrics`` endpoint a single coherent document and
avoids pulling in another C extension.

All mutators are ``async`` and serialise through a module-level
``asyncio.Lock`` so concurrent ``observe_job`` calls from multiple
request tasks are race-free.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Histogram bucket upper bounds (ms). Tuned for the observed range of
# gatekeeper jobs: sub-second trivial proofs up to 15-minute pro/premium
# solver runs. The final ``+Inf`` bucket is appended automatically.
_DURATION_BUCKETS_MS: tuple[float, ...] = (
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    300_000.0,
    900_000.0,
)


def _empty_histogram() -> dict[str, Any]:
    """Return a zero-initialised histogram with the module's bucket set."""
    return {
        "buckets": {b: 0 for b in _DURATION_BUCKETS_MS},
        "inf": 0,
        "count": 0,
        "sum": 0.0,
    }


class GatekeeperMetrics:
    """Per-tier / per-result counters and histograms for gatekeeper jobs.

    Labels:

    * ``tier`` — agent tier at time of invocation (``free``, ``pro``,
      ``premium``, ``admin``; ``unknown`` when the caller did not pass a
      tier, which should only happen in tests).
    * ``result`` — ``satisfied`` / ``violated`` / ``error`` / ``timeout``
      / ``cancelled`` / ``unknown``. Failed jobs use the error reason
      here, not just ``"error"``.

    Series are built lazily the first time an ``(tier, result)`` pair is
    observed, so the exposition size scales with what is actually in use
    rather than the Cartesian product of every possible label.
    """

    # { (tier, result) -> int }
    _jobs_total: dict[tuple[str, str], int] = {}
    # { (tier, result) -> float }
    _cost_sum: dict[tuple[str, str], float] = {}
    # { (tier, result) -> histogram dict }
    _duration_histograms: dict[tuple[str, str], dict[str, Any]] = {}
    _solver_histograms: dict[tuple[str, str], dict[str, Any]] = {}

    _lock = asyncio.Lock()

    # -- mutators -----------------------------------------------------------

    @classmethod
    def reset(cls) -> None:
        """Zero all series. Synchronous for use in test setup/teardown."""
        cls._jobs_total = {}
        cls._cost_sum = {}
        cls._duration_histograms = {}
        cls._solver_histograms = {}

    @classmethod
    async def observe_job(
        cls,
        *,
        tier: str | None,
        result: str | None,
        cost_credits: float,
        duration_ms: float,
        solver_ms: float,
    ) -> None:
        """Record a single terminal gatekeeper job."""
        tier_label = tier or "unknown"
        result_label = result or "unknown"
        key = (tier_label, result_label)

        async with cls._lock:
            cls._jobs_total[key] = cls._jobs_total.get(key, 0) + 1
            cls._cost_sum[key] = cls._cost_sum.get(key, 0.0) + float(cost_credits)

            dh = cls._duration_histograms.setdefault(key, _empty_histogram())
            _record_observation(dh, float(duration_ms))

            sh = cls._solver_histograms.setdefault(key, _empty_histogram())
            _record_observation(sh, float(solver_ms))

    # -- exposition ----------------------------------------------------------

    @classmethod
    async def to_prometheus(cls) -> str:
        """Render all gatekeeper series in Prometheus 0.0.4 text format."""
        async with cls._lock:
            jobs_total = dict(cls._jobs_total)
            cost_sum = dict(cls._cost_sum)
            duration_hists = {k: _clone_hist(v) for k, v in cls._duration_histograms.items()}
            solver_hists = {k: _clone_hist(v) for k, v in cls._solver_histograms.items()}

        lines: list[str] = []

        # -- Counters -------------------------------------------------------
        lines.append("# HELP a2a_gatekeeper_jobs_total Gatekeeper verification jobs processed")
        lines.append("# TYPE a2a_gatekeeper_jobs_total counter")
        for (tier, result), count in sorted(jobs_total.items()):
            lines.append(f'a2a_gatekeeper_jobs_total{{tier="{tier}",result="{result}"}} {count}')

        lines.append("# HELP a2a_gatekeeper_cost_credits_sum Cumulative credits billed for gatekeeper jobs")
        lines.append("# TYPE a2a_gatekeeper_cost_credits_sum counter")
        for (tier, result), total in sorted(cost_sum.items()):
            lines.append(f'a2a_gatekeeper_cost_credits_sum{{tier="{tier}",result="{result}"}} {_format_number(total)}')

        # -- Histograms -----------------------------------------------------
        _emit_histogram(
            lines,
            metric="a2a_gatekeeper_duration_ms",
            help_text="End-to-end gatekeeper job duration (ms)",
            series=duration_hists,
        )
        _emit_histogram(
            lines,
            metric="a2a_gatekeeper_solver_ms",
            help_text="Z3 solver wall-clock time per gatekeeper job (ms)",
            series=solver_hists,
        )

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_observation(hist: dict[str, Any], value: float) -> None:
    hist["count"] += 1
    hist["sum"] += value
    placed = False
    for bucket in _DURATION_BUCKETS_MS:
        if value <= bucket:
            hist["buckets"][bucket] += 1
            placed = True
    if not placed:
        # Above every finite bucket — only +Inf catches it.
        pass
    hist["inf"] += 1


def _clone_hist(hist: dict[str, Any]) -> dict[str, Any]:
    return {
        "buckets": dict(hist["buckets"]),
        "inf": hist["inf"],
        "count": hist["count"],
        "sum": hist["sum"],
    }


def _emit_histogram(
    lines: list[str],
    *,
    metric: str,
    help_text: str,
    series: dict[tuple[str, str], dict[str, Any]],
) -> None:
    lines.append(f"# HELP {metric} {help_text}")
    lines.append(f"# TYPE {metric} histogram")
    if not series:
        # Emit empty count/sum so Prometheus still sees the metric exists.
        lines.append(f"{metric}_count 0")
        lines.append(f"{metric}_sum 0")
        return
    for (tier, result), hist in sorted(series.items()):
        # Prometheus histograms require buckets to be cumulative AND
        # monotonically non-decreasing. Since _record_observation already
        # increments every bucket ``>= value``, the dict values are
        # already cumulative.
        for bucket in _DURATION_BUCKETS_MS:
            lines.append(
                f'{metric}_bucket{{tier="{tier}",result="{result}",le="{_format_bucket(bucket)}"}} '
                f"{hist['buckets'][bucket]}"
            )
        lines.append(f'{metric}_bucket{{tier="{tier}",result="{result}",le="+Inf"}} {hist["inf"]}')
        lines.append(f'{metric}_count{{tier="{tier}",result="{result}"}} {hist["count"]}')
        lines.append(f'{metric}_sum{{tier="{tier}",result="{result}"}} {_format_number(hist["sum"])}')


def _format_bucket(value: float) -> str:
    # Use integer representation when possible so dashboard labels stay
    # clean (``le="100"`` rather than ``le="100.0"``).
    if value.is_integer():
        return str(int(value))
    return str(value)


def _format_number(value: float) -> str:
    """Format a float so whole numbers omit the trailing ``.0``."""
    if value == 0:
        return "0"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"
