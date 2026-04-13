"""Tests for v1.3.2 audit remediation — 4 findings fixed."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _register_identity(client, key, agent_id):
    return await client.post(
        "/v1/identity/agents",
        json={"agent_id": agent_id},
        headers={"Authorization": f"Bearer {key}"},
    )


# ===========================================================================
# Fix 1: Wallet-split — InsufficientCreditsError includes currency
# ===========================================================================


async def test_capture_usd_intent_insufficient_includes_currency(client, pro_api_key, app):
    """402 error for USD capture should mention the currency, not just 'credits'."""
    ctx = app.state.ctx
    # Create a second agent as payee
    await ctx.tracker.wallet.create("payee-agent-ws", initial_balance=0, signup_bonus=False)

    # Create intent in USD (pro-agent only has CREDITS, not USD)
    resp = await client.post(
        "/v1/payments/intents",
        json={"payer": "pro-agent", "payee": "payee-agent-ws", "amount": "1.00", "currency": "USD"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201
    intent_id = resp.json()["id"]

    # Capture should fail because pro-agent has no USD balance
    resp = await client.post(
        f"/v1/payments/intents/{intent_id}/capture",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert "USD" in body["detail"], f"Error should mention USD currency: {body['detail']}"


async def test_capture_credits_intent_succeeds(client, pro_api_key, app):
    """Capture with CREDITS (default) should succeed for a funded agent."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-agent-cr", initial_balance=0, signup_bonus=False)

    resp = await client.post(
        "/v1/payments/intents",
        json={"payer": "pro-agent", "payee": "payee-agent-cr", "amount": "1.00"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201
    intent_id = resp.json()["id"]

    resp = await client.post(
        f"/v1/payments/intents/{intent_id}/capture",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200


# ===========================================================================
# Fix 2: Idempotency key accepted in CreateIntentRequest body
# ===========================================================================


async def test_create_intent_idempotency_key_in_body(client, pro_api_key, app):
    """idempotency_key in request body should NOT be rejected as extra field."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-idem", initial_balance=0, signup_bonus=False)

    resp = await client.post(
        "/v1/payments/intents",
        json={
            "payer": "pro-agent",
            "payee": "payee-idem",
            "amount": "1.00",
            "idempotency_key": "test-idem-key-001",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.json()}"
    intent_id_1 = resp.json()["id"]

    # Same idempotency key should return same intent
    resp2 = await client.post(
        "/v1/payments/intents",
        json={
            "payer": "pro-agent",
            "payee": "payee-idem",
            "amount": "1.00",
            "idempotency_key": "test-idem-key-001",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp2.status_code == 201
    assert resp2.json()["id"] == intent_id_1


# ===========================================================================
# Fix 3: Performance escrow conditions field accepted
# ===========================================================================


async def test_performance_escrow_conditions_accepted(client, pro_api_key, app):
    """conditions field in performance escrow should NOT be rejected."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-perf", initial_balance=0, signup_bonus=False)

    resp = await client.post(
        "/v1/payments/escrows/performance",
        json={
            "payer": "pro-agent",
            "payee": "payee-perf",
            "amount": "10.00",
            "metric_name": "accuracy",
            "threshold": ">=0.95",
            "conditions": {"min_samples": 100},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.json()}"


async def test_performance_escrow_without_conditions(client, pro_api_key, app):
    """Performance escrow should still work without conditions."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-perf2", initial_balance=0, signup_bonus=False)

    resp = await client.post(
        "/v1/payments/escrows/performance",
        json={
            "payer": "pro-agent",
            "payee": "payee-perf2",
            "amount": "10.00",
            "metric_name": "accuracy",
            "threshold": ">=0.95",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201)


# ===========================================================================
# Fix 4: Metrics ingest accepts common metric names
# ===========================================================================


async def test_metrics_ingest_common_names(client, pro_api_key):
    """Common metric names like latency_ms, throughput_rps should be accepted."""
    await _register_identity(client, pro_api_key, "pro-agent")
    resp = await client.post(
        "/v1/identity/metrics/ingest",
        json={
            "agent_id": "pro-agent",
            "metrics": {"latency_ms": 150.0, "throughput_rps": 1000.0},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 2, f"Expected 2 accepted, got {body}"
    assert body["rejected"] == 0


async def test_metrics_ingest_custom_names(client, pro_api_key):
    """Custom metric names like accuracy, custom_xyz should be accepted."""
    await _register_identity(client, pro_api_key, "pro-agent")
    resp = await client.post(
        "/v1/identity/metrics/ingest",
        json={
            "agent_id": "pro-agent",
            "metrics": {"accuracy": 0.95, "error_rate": 0.02},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 2, f"Expected 2 accepted, got {body}"


async def test_metrics_ingest_original_names_still_work(client, pro_api_key):
    """Original hardcoded metrics should still be accepted."""
    await _register_identity(client, pro_api_key, "pro-agent")
    resp = await client.post(
        "/v1/identity/metrics/ingest",
        json={
            "agent_id": "pro-agent",
            "metrics": {"sharpe_30d": 1.5, "aum": 100000.0},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 2
