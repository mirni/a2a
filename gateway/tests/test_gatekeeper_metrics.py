"""Prometheus histogram + counter metrics for gatekeeper operations.

v1.2.4 telemetry: surface gatekeeper cost + solver time broken down by
agent tier and outcome so SRE can alert on things like "pro-tier failure
rate > 5%" and the CMO can see what each tier is actually paying for.

Metrics added:

* ``a2a_gatekeeper_jobs_total{tier,result}``        — counter
* ``a2a_gatekeeper_cost_credits_sum{tier,result}``  — summed credits
* ``a2a_gatekeeper_duration_ms{tier,result}``       — bucketed histogram
* ``a2a_gatekeeper_solver_ms{tier,result}``         — bucketed histogram
"""

from __future__ import annotations

import asyncio

import pytest

from gateway.src.gatekeeper_metrics import GatekeeperMetrics


@pytest.fixture(autouse=True)
def _reset_gatekeeper_metrics():
    GatekeeperMetrics.reset()
    yield
    GatekeeperMetrics.reset()


@pytest.mark.asyncio
async def test_observe_job_counts_by_tier_and_result():
    await GatekeeperMetrics.observe_job(
        tier="pro",
        result="satisfied",
        cost_credits=12.0,
        duration_ms=340.0,
        solver_ms=120.0,
    )
    await GatekeeperMetrics.observe_job(
        tier="pro",
        result="satisfied",
        cost_credits=12.0,
        duration_ms=400.0,
        solver_ms=180.0,
    )
    await GatekeeperMetrics.observe_job(
        tier="pro",
        result="violated",
        cost_credits=12.0,
        duration_ms=210.0,
        solver_ms=60.0,
    )
    await GatekeeperMetrics.observe_job(
        tier="premium",
        result="satisfied",
        cost_credits=14.0,
        duration_ms=500.0,
        solver_ms=250.0,
    )

    text = await GatekeeperMetrics.to_prometheus()
    assert 'a2a_gatekeeper_jobs_total{tier="pro",result="satisfied"} 2' in text
    assert 'a2a_gatekeeper_jobs_total{tier="pro",result="violated"} 1' in text
    assert 'a2a_gatekeeper_jobs_total{tier="premium",result="satisfied"} 1' in text


@pytest.mark.asyncio
async def test_cost_credits_sum_per_tier_and_result():
    await GatekeeperMetrics.observe_job(
        tier="pro", result="satisfied", cost_credits=12.0, duration_ms=1, solver_ms=1
    )
    await GatekeeperMetrics.observe_job(
        tier="pro", result="satisfied", cost_credits=18.0, duration_ms=1, solver_ms=1
    )
    text = await GatekeeperMetrics.to_prometheus()
    # Sums are reported as floats, so string-match the full line.
    assert 'a2a_gatekeeper_cost_credits_sum{tier="pro",result="satisfied"} 30' in text


@pytest.mark.asyncio
async def test_duration_histogram_exposes_buckets():
    """Solver and wall-clock durations appear as Prometheus histogram buckets."""
    # Two completed jobs with different latencies land in different buckets.
    await GatekeeperMetrics.observe_job(
        tier="pro", result="satisfied", cost_credits=12.0, duration_ms=100.0, solver_ms=40.0
    )
    await GatekeeperMetrics.observe_job(
        tier="pro", result="satisfied", cost_credits=12.0, duration_ms=2500.0, solver_ms=800.0
    )
    text = await GatekeeperMetrics.to_prometheus()

    # Every histogram must publish _bucket, _count, _sum lines.
    assert "a2a_gatekeeper_duration_ms_bucket" in text
    assert "a2a_gatekeeper_duration_ms_count" in text
    assert "a2a_gatekeeper_duration_ms_sum" in text
    assert "a2a_gatekeeper_solver_ms_bucket" in text
    assert "a2a_gatekeeper_solver_ms_count" in text
    assert "a2a_gatekeeper_solver_ms_sum" in text

    # Bucket cumulative monotonicity sanity check: the +Inf bucket for
    # the pro/satisfied series must include both samples.
    for line in text.splitlines():
        if line.startswith(
            'a2a_gatekeeper_duration_ms_bucket{tier="pro",result="satisfied",le="+Inf"}'
        ):
            value = int(line.split()[-1])
            assert value == 2, line
            break
    else:
        pytest.fail("pro/satisfied +Inf bucket line missing")


@pytest.mark.asyncio
async def test_metrics_exposition_type_headers():
    """Every metric emits the required # HELP / # TYPE preamble."""
    await GatekeeperMetrics.observe_job(
        tier="free", result="error", cost_credits=0.0, duration_ms=10, solver_ms=0
    )
    text = await GatekeeperMetrics.to_prometheus()
    for metric in (
        "a2a_gatekeeper_jobs_total",
        "a2a_gatekeeper_cost_credits_sum",
        "a2a_gatekeeper_duration_ms",
        "a2a_gatekeeper_solver_ms",
    ):
        assert f"# HELP {metric}" in text
        assert f"# TYPE {metric}" in text


@pytest.mark.asyncio
async def test_observe_job_is_async_safe_under_concurrency():
    async def _bump():
        for _ in range(50):
            await GatekeeperMetrics.observe_job(
                tier="pro",
                result="satisfied",
                cost_credits=1.0,
                duration_ms=1.0,
                solver_ms=1.0,
            )

    await asyncio.gather(*(_bump() for _ in range(5)))
    text = await GatekeeperMetrics.to_prometheus()
    assert 'a2a_gatekeeper_jobs_total{tier="pro",result="satisfied"} 250' in text
    assert 'a2a_gatekeeper_cost_credits_sum{tier="pro",result="satisfied"} 250' in text


@pytest.mark.asyncio
async def test_unknown_tier_falls_back_to_unknown_label():
    """Callers passing None/empty tier get bucketed under 'unknown'."""
    await GatekeeperMetrics.observe_job(
        tier=None,  # type: ignore[arg-type]
        result="satisfied",
        cost_credits=12.0,
        duration_ms=10,
        solver_ms=1,
    )
    text = await GatekeeperMetrics.to_prometheus()
    assert 'tier="unknown"' in text


# ---------------------------------------------------------------------------
# Integration — route wiring + /v1/metrics exposition
# ---------------------------------------------------------------------------


_JSON_POLICY_SAT = (
    '{"name":"positive","variables":[{"name":"x","type":"int","value":5}],'
    '"assertions":[{"op":">","args":["x",0]}]}'
)


@pytest.mark.asyncio
async def test_submit_verification_records_gatekeeper_metrics(client, pro_api_key):
    """POST /v1/gatekeeper/jobs should bump a2a_gatekeeper_jobs_total."""
    GatekeeperMetrics.reset()
    resp = await client.post(
        "/v1/gatekeeper/jobs",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={
            "agent_id": "pro-agent",
            "properties": [
                {"name": "positive", "language": "json_policy", "expression": _JSON_POLICY_SAT}
            ],
        },
    )
    assert resp.status_code in (200, 201), resp.text

    text = await GatekeeperMetrics.to_prometheus()
    assert 'a2a_gatekeeper_jobs_total{tier="pro",result="satisfied"} 1' in text, text


@pytest.mark.asyncio
async def test_gatekeeper_metrics_surface_in_metrics_endpoint(client, pro_api_key):
    """Gatekeeper histograms must show up in /v1/metrics."""
    GatekeeperMetrics.reset()
    await client.post(
        "/v1/gatekeeper/jobs",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={
            "agent_id": "pro-agent",
            "properties": [
                {"name": "positive", "language": "json_policy", "expression": _JSON_POLICY_SAT}
            ],
        },
    )
    metrics_resp = await client.get("/v1/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text
    assert "a2a_gatekeeper_jobs_total" in body
    assert "a2a_gatekeeper_duration_ms_bucket" in body
    assert "a2a_gatekeeper_solver_ms_bucket" in body
    assert 'tier="pro"' in body
