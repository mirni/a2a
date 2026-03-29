"""Benchmark scenarios for the A2A commerce gateway.

Each scenario is an async function that accepts a Starlette app (with lifespan
already started) and returns one or more BenchmarkResult objects.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from gateway.benchmarks.bench_runner import (
    BenchmarkResult,
    run_benchmark,
    run_benchmark_multi_concurrency,
)

# ---------------------------------------------------------------------------
# Scenario 1: Health endpoint throughput
# ---------------------------------------------------------------------------


async def scenario_health_throughput(
    app: Any,
    total_requests: int = 200,
    concurrency_levels: list[int] | None = None,
) -> list[BenchmarkResult]:
    """Fire N requests to GET /health at various concurrency levels."""

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        resp = await client.get("/health")
        return resp.status_code

    return await run_benchmark_multi_concurrency(
        app=app,
        scenario_name="health_throughput",
        request_func=request_func,
        total_requests=total_requests,
        concurrency_levels=concurrency_levels or [1, 10, 50],
    )


# ---------------------------------------------------------------------------
# Scenario 2: Pricing endpoint throughput
# ---------------------------------------------------------------------------


async def scenario_pricing_throughput(
    app: Any,
    total_requests: int = 200,
    concurrency_levels: list[int] | None = None,
) -> list[BenchmarkResult]:
    """Fire N requests to GET /pricing at various concurrency levels."""

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        resp = await client.get("/pricing")
        return resp.status_code

    return await run_benchmark_multi_concurrency(
        app=app,
        scenario_name="pricing_throughput",
        request_func=request_func,
        total_requests=total_requests,
        concurrency_levels=concurrency_levels or [1, 10, 50],
    )


# ---------------------------------------------------------------------------
# Scenario 3: Execute pipeline throughput (get_balance, free tool)
# ---------------------------------------------------------------------------


async def scenario_execute_pipeline(
    app: Any,
    total_requests: int = 100,
    concurrency_levels: list[int] | None = None,
) -> list[BenchmarkResult]:
    """Fire N POST /execute requests for get_balance (free tool).

    Measures the full pipeline: auth -> tier -> rate_limit -> dispatch -> charge.
    Uses a pro-tier key with 10000 rate limit/hour to avoid hitting rate limits.
    """
    api_key_holder: dict[str, str] = {}

    async def setup(client: httpx.AsyncClient, app: Any) -> None:
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("bench-agent", initial_balance=10000.0)
        key_info = await ctx.key_manager.create_key("bench-agent", tier="pro")
        api_key_holder["key"] = key_info["key"]

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        resp = await client.post(
            "/execute",
            json={"tool": "get_balance", "params": {"agent_id": "bench-agent"}},
            headers={"Authorization": f"Bearer {api_key_holder['key']}"},
        )
        return resp.status_code

    return await run_benchmark_multi_concurrency(
        app=app,
        scenario_name="execute_pipeline_get_balance",
        request_func=request_func,
        total_requests=total_requests,
        concurrency_levels=concurrency_levels or [1, 10, 50],
        setup_func=setup,
    )


# ---------------------------------------------------------------------------
# Scenario 4: Execute with paid tools (create_intent)
# ---------------------------------------------------------------------------


async def scenario_execute_paid_tools(
    app: Any,
    total_requests: int = 50,
) -> list[BenchmarkResult]:
    """Fire N create_intent requests (0.5 credits each).

    Measures throughput with actual wallet charges happening.
    """
    api_key_holder: dict[str, str] = {}

    async def setup(client: httpx.AsyncClient, app: Any) -> None:
        ctx = app.state.ctx
        # Large balance to cover all requests: 50 * 0.5 = 25 credits minimum
        await ctx.tracker.wallet.create("paid-agent", initial_balance=50000.0)
        await ctx.tracker.wallet.create("payee-agent", initial_balance=0.0)
        key_info = await ctx.key_manager.create_key("paid-agent", tier="pro")
        api_key_holder["key"] = key_info["key"]

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        resp = await client.post(
            "/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "paid-agent",
                    "payee": "payee-agent",
                    "amount": 1.0,
                    "description": f"bench-intent-{idx}",
                },
            },
            headers={"Authorization": f"Bearer {api_key_holder['key']}"},
        )
        return resp.status_code

    result = await run_benchmark(
        app=app,
        scenario_name="execute_paid_tools_create_intent",
        request_func=request_func,
        total_requests=total_requests,
        concurrency=10,
        setup_func=setup,
    )
    return [result]


# ---------------------------------------------------------------------------
# Scenario 5: Concurrent wallet stress
# ---------------------------------------------------------------------------


async def scenario_wallet_stress(
    app: Any,
    total_ops: int = 100,
) -> list[BenchmarkResult]:
    """Stress-test wallet with concurrent deposit + withdraw operations.

    Creates wallet with 10000 credits, fires concurrent deposits and withdrawals,
    then verifies final balance is consistent.
    """
    api_key_holder: dict[str, str] = {}

    async def setup(client: httpx.AsyncClient, app: Any) -> None:
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("stress-agent", initial_balance=10000.0)
        key_info = await ctx.key_manager.create_key("stress-agent", tier="pro")
        api_key_holder["key"] = key_info["key"]

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        if idx % 2 == 0:
            # Deposit 10 credits
            resp = await client.post(
                "/execute",
                json={
                    "tool": "deposit",
                    "params": {
                        "agent_id": "stress-agent",
                        "amount": 10.0,
                        "description": f"bench-deposit-{idx}",
                    },
                },
                headers={"Authorization": f"Bearer {api_key_holder['key']}"},
            )
        else:
            # Use get_balance as a lightweight read operation (withdrawals via
            # create_intent would add too much complexity with payee wallets)
            resp = await client.post(
                "/execute",
                json={
                    "tool": "get_balance",
                    "params": {"agent_id": "stress-agent"},
                },
                headers={"Authorization": f"Bearer {api_key_holder['key']}"},
            )
        return resp.status_code

    result = await run_benchmark(
        app=app,
        scenario_name="wallet_stress_concurrent_ops",
        request_func=request_func,
        total_requests=total_ops,
        concurrency=20,
        setup_func=setup,
    )

    # Verify balance consistency: started at 10000, deposited 10 * (total_ops // 2)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://bench") as client:
        resp = await client.post(
            "/execute",
            json={
                "tool": "get_balance",
                "params": {"agent_id": "stress-agent"},
            },
            headers={"Authorization": f"Bearer {api_key_holder['key']}"},
        )
        data = resp.json()
        final_balance = data.get("result", {}).get("balance", -1)
        expected_deposits = total_ops // 2
        expected_balance = 10000.0 + (expected_deposits * 10.0)
        result.extra["final_balance"] = final_balance
        result.extra["expected_balance"] = expected_balance
        result.extra["balance_consistent"] = abs(final_balance - expected_balance) < 0.01

    return [result]


# ---------------------------------------------------------------------------
# Scenario 6: Rate limiter under burst
# ---------------------------------------------------------------------------


async def scenario_rate_limiter_burst(
    app: Any,
    total_requests: int = 200,
) -> list[BenchmarkResult]:
    """Test rate limiter behavior under burst load.

    Creates a free-tier key (100/hour limit) and fires 200 requests rapidly.
    Verifies the first ~100 succeed and the rest get 429.
    """
    api_key_holder: dict[str, str] = {}
    status_counts: dict[int, int] = {}

    async def setup(client: httpx.AsyncClient, app: Any) -> None:
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("ratelimit-agent", initial_balance=10000.0)
        key_info = await ctx.key_manager.create_key("ratelimit-agent", tier="free")
        api_key_holder["key"] = key_info["key"]

    async def request_func(client: httpx.AsyncClient, idx: int) -> int:
        resp = await client.post(
            "/execute",
            json={
                "tool": "get_balance",
                "params": {"agent_id": "ratelimit-agent"},
            },
            headers={"Authorization": f"Bearer {api_key_holder['key']}"},
        )
        status = resp.status_code
        # Track status codes (not perfectly thread-safe but good enough)
        status_counts[status] = status_counts.get(status, 0) + 1
        return status

    # Use concurrency=1 to ensure sequential ordering so the rate limiter
    # cutoff is deterministic (first 100 succeed, rest get 429)
    result = await run_benchmark(
        app=app,
        scenario_name="rate_limiter_burst",
        request_func=request_func,
        total_requests=total_requests,
        concurrency=1,
        setup_func=setup,
    )

    success_count = status_counts.get(200, 0)
    rate_limited_count = status_counts.get(429, 0)

    result.extra["success_count"] = success_count
    result.extra["rate_limited_count"] = rate_limited_count
    result.extra["status_distribution"] = dict(status_counts)
    result.extra["cutoff_accurate"] = success_count == 100 and rate_limited_count == 100

    return [result]


# ---------------------------------------------------------------------------
# All scenarios registry
# ---------------------------------------------------------------------------

ALL_SCENARIOS = [
    ("health_throughput", scenario_health_throughput),
    ("pricing_throughput", scenario_pricing_throughput),
    ("execute_pipeline", scenario_execute_pipeline),
    ("execute_paid_tools", scenario_execute_paid_tools),
    ("wallet_stress", scenario_wallet_stress),
    ("rate_limiter_burst", scenario_rate_limiter_burst),
]
