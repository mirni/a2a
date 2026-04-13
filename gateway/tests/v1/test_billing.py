"""Tests for billing REST endpoints — /v1/billing/."""

from __future__ import annotations

import pytest

from gateway.src.deps.billing import BalanceError, calculate_tool_cost

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for calculate_tool_cost
# ---------------------------------------------------------------------------


class TestCalculateToolCost:
    def test_flat_pricing_basic(self):
        pricing = {"per_call": 0.5}
        assert calculate_tool_cost(pricing, {}) == 0.5

    def test_flat_pricing_zero(self):
        pricing = {"per_call": 0}
        assert calculate_tool_cost(pricing, {}) == 0.0

    def test_flat_pricing_negative_clamped(self):
        pricing = {"per_call": -1}
        assert calculate_tool_cost(pricing, {}) == 0.0

    def test_flat_pricing_empty(self):
        assert calculate_tool_cost({}, {}) == 0.0

    def test_percentage_pricing_basic(self):
        pricing = {"model": "percentage", "percentage": 10, "min_fee": 0, "max_fee": 100}
        # 10% of 200 = 20
        assert calculate_tool_cost(pricing, {"amount": 200}) == 20.0

    def test_percentage_pricing_min_fee_clamp(self):
        pricing = {"model": "percentage", "percentage": 1, "min_fee": 5, "max_fee": 100}
        # 1% of 100 = 1, clamped to min_fee=5
        assert calculate_tool_cost(pricing, {"amount": 100}) == 5.0

    def test_percentage_pricing_max_fee_clamp(self):
        pricing = {"model": "percentage", "percentage": 50, "min_fee": 0, "max_fee": 10}
        # 50% of 100 = 50, clamped to max_fee=10
        assert calculate_tool_cost(pricing, {"amount": 100}) == 10.0

    def test_percentage_pricing_zero_amount(self):
        pricing = {"model": "percentage", "percentage": 10, "min_fee": 0, "max_fee": 100}
        # 10% of 0 = 0
        assert calculate_tool_cost(pricing, {"amount": 0}) == 0.0

    def test_percentage_pricing_min_fee_on_zero_amount(self):
        pricing = {"model": "percentage", "percentage": 10, "min_fee": 1.0, "max_fee": 100}
        # 10% of 0 = 0, clamped to min_fee=1.0
        assert calculate_tool_cost(pricing, {"amount": 0}) == 1.0

    def test_balance_error_attributes(self):
        err = BalanceError("Insufficient balance: 0 < 10")
        assert err.message == "Insufficient balance: 0 < 10"
        assert "0 < 10" in str(err)


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


async def test_create_wallet_via_rest(client, app):
    """Creating a wallet requires ownership — caller must match agent_id."""
    ctx = app.state.ctx
    # Create a key for a new agent (no wallet yet)
    key_info = await ctx.key_manager.create_key("new-wallet-agent", tier="free")
    resp = await client.post(
        "/v1/billing/wallets",
        json={"agent_id": "new-wallet-agent"},
        headers={"Authorization": f"Bearer {key_info['key']}"},
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
    # Audit M1: deposit response must include transaction_id so clients can
    # look up the recorded ledger row without a follow-up list call.
    assert "transaction_id" in body
    assert isinstance(body["transaction_id"], int)


async def test_deposit_idempotency_key(client, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Idempotency-Key": "dep-123"}
    resp1 = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": "10.00"},
        headers=headers,
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    bal1 = body1["new_balance"]
    txn1 = body1["transaction_id"]
    # Second call with same key should be idempotent
    resp2 = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": "10.00"},
        headers=headers,
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    bal2 = body2["new_balance"]
    assert bal1 == bal2
    # Audit M1: the same transaction_id must be echoed on the replayed call.
    assert body2["transaction_id"] == txn1


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


async def test_get_exchange_rate_unsupported_currency_returns_400(client, api_key):
    """SOL is not a supported currency — should return 400, not 500."""
    resp = await client.get(
        "/v1/billing/exchange-rates?from_currency=SOL&to_currency=USD",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "SOL" in body.get("detail", "")


async def test_get_exchange_rate_dogecoin_returns_400(client, api_key):
    """DOGECOIN is not a valid currency code — should return 400."""
    resp = await client.get(
        "/v1/billing/exchange-rates?from_currency=DOGECOIN&to_currency=CREDITS",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400


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


# ---------------------------------------------------------------------------
# B1: ConvertCurrency amount validation
# ---------------------------------------------------------------------------


class TestConvertCurrencyAmountValidation:
    """ConvertCurrencyRequest must reject amount <= 0, > 1 billion, and > 2 decimal places."""

    async def test_convert_negative_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/convert",
            json={"amount": "-10", "from_currency": "CREDITS", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_convert_zero_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/convert",
            json={"amount": "0", "from_currency": "CREDITS", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_convert_overflow_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/convert",
            json={"amount": "1000000001", "from_currency": "CREDITS", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_convert_excessive_precision_rejected(self, client, api_key):
        """Amounts with >8 decimal places must be rejected (crypto precision limit)."""
        resp = await client.post(
            "/v1/billing/wallets/test-agent/convert",
            json={"amount": "10.000000001", "from_currency": "CREDITS", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AMT-500: Negative/zero amounts must be rejected with 422
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RACE-DEP: Concurrent deposits must not lose credits
# ---------------------------------------------------------------------------


class TestConcurrentDeposits:
    """Concurrent deposits must all be accounted for — no lost updates."""

    async def test_concurrent_deposits_via_rest(self, client, api_key, app):
        """10 concurrent deposits of 1.0 each must increase balance by exactly 10.0."""
        import asyncio

        # Record initial balance
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        initial_balance = float(resp.json()["balance"])

        # Fire 10 concurrent deposit requests
        async def deposit_one(i: int):
            return await client.post(
                "/v1/billing/wallets/test-agent/deposit",
                json={"amount": "1.00"},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Idempotency-Key": f"race-dep-{i}",
                },
            )

        results = await asyncio.gather(*[deposit_one(i) for i in range(10)])
        # All should succeed
        for r in results:
            assert r.status_code == 200, f"Deposit failed: {r.json()}"

        # Check final balance
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        final_balance = float(resp.json()["balance"])
        assert final_balance == pytest.approx(initial_balance + 10.0, abs=0.01), (
            f"Lost deposits: expected {initial_balance + 10.0}, got {final_balance}"
        )


class TestAmountValidation:
    """Deposit and withdraw must reject non-positive amounts at the Pydantic layer."""

    async def test_deposit_negative_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "-100"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_deposit_zero_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "0"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_deposit_small_negative_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "-0.01"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_withdraw_negative_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/withdraw",
            json={"amount": "-100"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_withdraw_zero_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/withdraw",
            json={"amount": "0"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_deposit_positive_amount_accepted(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "1.00"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

    async def test_deposit_huge_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "1e18"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_deposit_over_billion_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "999999999999.99"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_withdraw_huge_amount_rejected(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/withdraw",
            json={"amount": "1e18"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_withdraw_insufficient_balance_returns_402(self, app, api_key):
        """Audit H1: overdraft must return 402 insufficient_balance, not 500.

        Uses a dedicated httpx client with raise_app_exceptions=False so the
        registered exception handler's response is returned rather than the
        raw exception (production behaviour).
        """
        import httpx

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/v1/billing/wallets/test-agent/withdraw",
                json={"amount": "99999.00"},
                headers={"Authorization": f"Bearer {api_key}"},
            )
        assert resp.status_code == 402, f"expected 402, got {resp.status_code} body={resp.text[:200]}"
        assert resp.headers.get("content-type", "").startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 402
        assert body["type"].endswith("/insufficient-balance")

    async def test_deposit_excessive_precision_rejected(self, client, api_key):
        """Amounts with >8 decimal places must be rejected (crypto precision limit)."""
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "0.000000001"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_deposit_two_decimal_accepted(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "0.01"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

    async def test_deposit_max_amount_accepted(self, client, api_key):
        """Free-tier deposit at the tier limit (1000) should be accepted."""
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "1000"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

    async def test_deposit_dogecoin_rejected(self, client, api_key):
        """DOGECOIN is not a valid currency — must be rejected."""
        resp = await client.post(
            "/v1/billing/wallets/test-agent/deposit",
            json={"amount": "10", "currency": "DOGECOIN"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert "DOGECOIN" in resp.json().get("detail", "")

    async def test_withdraw_invalid_currency_rejected(self, client, api_key):
        """Invalid currencies must be rejected on withdraw too."""
        resp = await client.post(
            "/v1/billing/wallets/test-agent/withdraw",
            json={"amount": "1", "currency": "MONOPOLY"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert "MONOPOLY" in resp.json().get("detail", "")
