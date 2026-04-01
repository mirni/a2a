"""Tests for billing REST endpoints — /v1/billing/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/balance
# ---------------------------------------------------------------------------


async def test_get_balance_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "balance" in body
    # Monetary value serialized as string
    assert isinstance(body["balance"], str)


async def test_get_balance_with_currency(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance?currency=USD",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "balance" in body


async def test_get_balance_no_auth(client):
    resp = await client.get("/v1/billing/wallets/test-agent/balance")
    assert resp.status_code == 401


async def test_get_balance_invalid_key(client):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": "Bearer bad-key"},
    )
    assert resp.status_code == 401


async def test_get_balance_headers(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
    assert "X-RateLimit-Limit" in resp.headers


# ---------------------------------------------------------------------------
# POST /v1/billing/wallets
# ---------------------------------------------------------------------------


async def test_create_wallet_via_rest(client, api_key):
    resp = await client.post(
        "/v1/billing/wallets",
        json={"agent_id": "new-agent-rest"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201


async def test_create_wallet_extra_fields_rejected(client, api_key):
    resp = await client.post(
        "/v1/billing/wallets",
        json={"agent_id": "x", "unknown_field": 1},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/billing/wallets/{agent_id}/deposit
# ---------------------------------------------------------------------------


async def test_deposit_via_rest(client, api_key):
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": "50.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "X-Charged" in resp.headers
    body = resp.json()
    assert "new_balance" in body


async def test_deposit_idempotency_key(client, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Idempotency-Key": "dep-123"}
    resp1 = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": "10.00"},
        headers=headers,
    )
    assert resp1.status_code == 200
    bal1 = resp1.json()["new_balance"]
    # Second call with same key should be idempotent
    resp2 = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": "10.00"},
        headers=headers,
    )
    assert resp2.status_code == 200
    bal2 = resp2.json()["new_balance"]
    assert bal1 == bal2


# ---------------------------------------------------------------------------
# POST /v1/billing/wallets/{agent_id}/withdraw
# ---------------------------------------------------------------------------


async def test_withdraw_via_rest(client, api_key):
    resp = await client.post(
        "/v1/billing/wallets/test-agent/withdraw",
        json={"amount": "10.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "new_balance" in body


# ---------------------------------------------------------------------------
# POST /v1/billing/wallets/{agent_id}/freeze & unfreeze
# ---------------------------------------------------------------------------


async def test_freeze_unfreeze_wallet(client, admin_api_key):
    resp = await client.post(
        "/v1/billing/wallets/admin-agent/freeze",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["frozen"] is True

    resp2 = await client.post(
        "/v1/billing/wallets/admin-agent/unfreeze",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["frozen"] is False


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/transactions
# ---------------------------------------------------------------------------


async def test_get_transactions_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/transactions",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "transactions" in body


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/usage
# ---------------------------------------------------------------------------


async def test_get_usage_summary_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/usage",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/analytics
# ---------------------------------------------------------------------------


async def test_get_service_analytics_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/analytics",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_calls" in body


# ---------------------------------------------------------------------------
# PUT/GET /v1/billing/wallets/{agent_id}/budget
# ---------------------------------------------------------------------------


async def test_set_and_get_budget(client, api_key):
    resp = await client.put(
        "/v1/billing/wallets/test-agent/budget",
        json={"daily_cap": "100.00", "monthly_cap": "1000.00"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["daily_cap"] is not None

    resp2 = await client.get(
        "/v1/billing/wallets/test-agent/budget",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["agent_id"] == "test-agent"


# ---------------------------------------------------------------------------
# GET /v1/billing/leaderboard
# ---------------------------------------------------------------------------


async def test_get_leaderboard_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/leaderboard?metric=spend",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "leaderboard" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/billing/estimate
# ---------------------------------------------------------------------------


async def test_estimate_cost_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/estimate?tool_name=get_balance&quantity=10",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_cost" in body


# ---------------------------------------------------------------------------
# GET /v1/billing/exchange-rates
# ---------------------------------------------------------------------------


async def test_get_exchange_rate_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/exchange-rates?from_currency=CREDITS&to_currency=USD",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "rate" in body


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/revenue
# ---------------------------------------------------------------------------


async def test_get_revenue_report_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/revenue",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "total_revenue" in body


# ---------------------------------------------------------------------------
# GET /v1/billing/wallets/{agent_id}/timeseries
# ---------------------------------------------------------------------------


async def test_get_timeseries_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/wallets/test-agent/timeseries?interval=hour",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "buckets" in body


# ---------------------------------------------------------------------------
# POST /v1/billing/wallets/{agent_id}/convert
# ---------------------------------------------------------------------------


async def test_convert_currency_via_rest(client, api_key):
    resp = await client.post(
        "/v1/billing/wallets/test-agent/convert",
        json={"amount": "10.00", "from_currency": "CREDITS", "to_currency": "USD"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/billing/discounts
# ---------------------------------------------------------------------------


async def test_get_volume_discount_via_rest(client, api_key):
    resp = await client.get(
        "/v1/billing/discounts?agent_id=test-agent&tool_name=get_balance&quantity=10",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "discount_pct" in body
