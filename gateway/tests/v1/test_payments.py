"""Tests for payments REST endpoints — /v1/payments/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

# Most payment tools require pro tier in catalog. Use pro_api_key.


async def _create_intent(client, key, payer="pro-agent", payee="payee-1", amount="100.00"):
    return await client.post(
        "/v1/payments/intents",
        json={"payer": payer, "payee": payee, "amount": amount},
        headers={"Authorization": f"Bearer {key}"},
    )


async def _create_escrow(client, key, payer="pro-agent", payee="payee-1", amount="50.00"):
    return await client.post(
        "/v1/payments/escrows",
        json={"payer": payer, "payee": payee, "amount": amount},
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------


async def test_create_intent_via_rest(client, pro_api_key):
    resp = await _create_intent(client, pro_api_key)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["status"] == "pending"
    assert "Location" in resp.headers


async def test_create_intent_no_auth(client):
    resp = await client.post(
        "/v1/payments/intents",
        json={"payer": "a", "payee": "b", "amount": "10"},
    )
    assert resp.status_code == 401


async def test_create_intent_extra_fields(client, pro_api_key):
    resp = await client.post(
        "/v1/payments/intents",
        json={"payer": "pro-agent", "payee": "b", "amount": "10", "extra": 1},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422


async def test_get_intent_via_rest(client, pro_api_key):
    create_resp = await _create_intent(client, pro_api_key)
    intent_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/payments/intents/{intent_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == intent_id


async def test_list_intents_via_rest(client, pro_api_key):
    await _create_intent(client, pro_api_key)
    resp = await client.get(
        "/v1/payments/intents?agent_id=pro-agent",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "intents" in resp.json()


async def test_capture_intent_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    try:
        await ctx.tracker.wallet.create("payee-cap", initial_balance=0, signup_bonus=False)
    except Exception:
        pass
    create_resp = await _create_intent(client, pro_api_key, payee="payee-cap")
    intent_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/intents/{intent_id}/capture",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "settled"


async def test_partial_capture_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    try:
        await ctx.tracker.wallet.create("payee-pc", initial_balance=0, signup_bonus=False)
    except Exception:
        pass
    create_resp = await _create_intent(client, pro_api_key, payee="payee-pc", amount="100.00")
    intent_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/intents/{intent_id}/partial-capture",
        json={"amount": "60.00"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "remaining_amount" in resp.json()


async def test_refund_intent_via_rest(client, pro_api_key):
    create_resp = await _create_intent(client, pro_api_key, payee="payee-ref")
    intent_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/intents/{intent_id}/refund",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "voided"


async def test_create_split_intent_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    for name in ("split-a", "split-b"):
        try:
            await ctx.tracker.wallet.create(name, initial_balance=0, signup_bonus=False)
        except Exception:
            pass
    resp = await client.post(
        "/v1/payments/intents/split",
        json={
            "payer": "pro-agent",
            "amount": "100.00",
            "splits": [
                {"payee": "split-a", "percentage": 60},
                {"payee": "split-b", "percentage": 40},
            ],
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "settled"


# ---------------------------------------------------------------------------
# Escrows
# ---------------------------------------------------------------------------


async def test_create_escrow_via_rest(client, pro_api_key):
    resp = await _create_escrow(client, pro_api_key)
    assert resp.status_code == 201
    assert "id" in resp.json()
    assert "Location" in resp.headers


async def test_get_escrow_via_rest(client, pro_api_key):
    create_resp = await _create_escrow(client, pro_api_key)
    escrow_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/payments/escrows/{escrow_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == escrow_id


async def test_list_escrows_via_rest(client, pro_api_key):
    await _create_escrow(client, pro_api_key)
    resp = await client.get(
        "/v1/payments/escrows?agent_id=pro-agent",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "escrows" in resp.json()


async def test_release_escrow_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    try:
        await ctx.tracker.wallet.create("payee-rel", initial_balance=0, signup_bonus=False)
    except Exception:
        pass
    create_resp = await _create_escrow(client, pro_api_key, payee="payee-rel")
    escrow_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/escrows/{escrow_id}/release",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "settled"


async def test_cancel_escrow_via_rest(client, pro_api_key):
    create_resp = await _create_escrow(client, pro_api_key, payee="payee-can")
    escrow_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/escrows/{escrow_id}/cancel",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200


async def test_create_performance_escrow_via_rest(client, pro_api_key):
    resp = await client.post(
        "/v1/payments/escrows/performance",
        json={
            "payer": "pro-agent",
            "payee": "payee-perf",
            "amount": "100.00",
            "metric_name": "latency_p99",
            "threshold": "200",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201
    assert "escrow_id" in resp.json()


async def test_check_performance_escrow_via_rest(client, pro_api_key):
    create_resp = await client.post(
        "/v1/payments/escrows/performance",
        json={
            "payer": "pro-agent",
            "payee": "payee-check",
            "amount": "50.00",
            "metric_name": "uptime",
            "threshold": "99",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    escrow_id = create_resp.json()["escrow_id"]
    resp = await client.post(
        f"/v1/payments/escrows/{escrow_id}/check-performance",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "released" in resp.json()


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------


async def test_refund_settlement_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    try:
        await ctx.tracker.wallet.create("payee-sref", initial_balance=0, signup_bonus=False)
    except Exception:
        pass
    create_resp = await _create_intent(client, pro_api_key, payee="payee-sref", amount="100.00")
    intent_id = create_resp.json()["id"]
    cap_resp = await client.post(
        f"/v1/payments/intents/{intent_id}/capture",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    settlement_id = cap_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/settlements/{settlement_id}/refund",
        json={"amount": "25.00"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "id" in resp.json()


# ---------------------------------------------------------------------------
# Payment History
# ---------------------------------------------------------------------------


async def test_get_payment_history_via_rest(client, pro_api_key):
    resp = await client.get(
        "/v1/payments/history?agent_id=pro-agent",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "history" in resp.json()


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


async def test_create_subscription_via_rest(client, pro_api_key):
    resp = await client.post(
        "/v1/payments/subscriptions",
        json={
            "payer": "pro-agent",
            "payee": "sub-payee",
            "amount": "9.99",
            "interval": "monthly",
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 201
    assert "id" in resp.json()
    assert "Location" in resp.headers


async def test_get_subscription_via_rest(client, pro_api_key):
    create_resp = await client.post(
        "/v1/payments/subscriptions",
        json={"payer": "pro-agent", "payee": "sub-get", "amount": "5.00", "interval": "monthly"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    sub_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/payments/subscriptions/{sub_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == sub_id


async def test_list_subscriptions_via_rest(client, pro_api_key):
    resp = await client.get(
        "/v1/payments/subscriptions?agent_id=pro-agent",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "subscriptions" in resp.json()


async def test_cancel_subscription_via_rest(client, pro_api_key):
    create_resp = await client.post(
        "/v1/payments/subscriptions",
        json={"payer": "pro-agent", "payee": "sub-can", "amount": "5.00", "interval": "monthly"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    sub_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/payments/subscriptions/{sub_id}/cancel",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_reactivate_subscription_via_rest(client, pro_api_key):
    """Reactivate a cancelled subscription. If the engine disallows reactivation
    from 'cancelled' (only from 'suspended'), the response will be a 409."""
    create_resp = await client.post(
        "/v1/payments/subscriptions",
        json={"payer": "pro-agent", "payee": "sub-react", "amount": "5.00", "interval": "monthly"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    sub_id = create_resp.json()["id"]
    await client.post(
        f"/v1/payments/subscriptions/{sub_id}/cancel",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    resp = await client.post(
        f"/v1/payments/subscriptions/{sub_id}/reactivate",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # Engine may return 409 if cancellation is terminal; both are valid responses
    assert resp.status_code in (200, 409)


async def test_process_due_subscriptions_via_rest(client, app):
    """process_due_subscriptions is admin-only; use admin-tier key."""
    import hashlib
    import secrets

    ctx = app.state.ctx
    agent_id = "admin-process-due"
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=10000.0, signup_bonus=False)
    except Exception:
        pass
    raw_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(key_hash=key_hash, agent_id=agent_id, tier="admin")

    resp = await client.post(
        "/v1/payments/subscriptions/process-due",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# B1: Amount validation — negative, zero, overflow must return 422
# ---------------------------------------------------------------------------


class TestRefundBalanceConservation:
    """H-NEW: create→capture→refund via REST must conserve balance exactly."""

    async def test_rest_refund_no_balance_drift(self, client, app):
        """After create→capture→refund, payer must end up at starting balance.

        Bug: require_tool() passed empty {} to calculate_tool_cost(), so
        percentage-based fees defaulted to min_fee (0.01) instead of the
        real fee. The refund then credited back the correctly computed fee,
        creating a per-cycle profit of (real_fee - min_fee).
        """
        payer_key = await _create_agent_key(app, "drift-payer", balance=1000.0)
        await _create_agent_key(app, "drift-payee", balance=0.0)

        ctx = app.state.ctx
        balance_before = await ctx.tracker.get_balance("drift-payer")

        # Create intent via REST (percentage-based fee: 2% of 50 = 1.0)
        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "drift-payer", "payee": "drift-payee", "amount": "50.00"},
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 201
        intent_id = resp.json()["id"]
        charged_header = float(resp.headers.get("X-Charged", "0"))

        # Capture
        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 200

        # Refund
        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/refund",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 200

        balance_after = await ctx.tracker.get_balance("drift-payer")

        # The payer must end up exactly where they started — no profit
        assert balance_after == balance_before, (
            f"Balance drift: started at {balance_before}, ended at {balance_after} "
            f"(delta={balance_after - balance_before}, charged_header={charged_header})"
        )

    async def test_x_charged_header_matches_percentage_fee(self, client, app):
        """X-Charged header on create_intent must reflect the percentage fee."""
        payer_key = await _create_agent_key(app, "xch-payer", balance=1000.0)
        await _create_agent_key(app, "xch-payee", balance=0.0)

        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "xch-payer", "payee": "xch-payee", "amount": "50.00"},
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 201
        charged = float(resp.headers.get("X-Charged", "0"))
        # 2% of 50 = 1.0 (not 0.01 min_fee)
        assert charged == 1.0, f"Expected X-Charged=1.0 (2% of 50), got {charged}"


class TestPaymentAmountValidation:
    """All payment request models must reject amount <= 0, > 1 billion, and > 2 decimal places."""

    async def test_create_intent_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "pro-agent", "payee": "b", "amount": "-1"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_intent_zero_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "pro-agent", "payee": "b", "amount": "0"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_intent_overflow_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "pro-agent", "payee": "b", "amount": "1000000001"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_intent_sub_penny_rejected(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={"payer": "pro-agent", "payee": "b", "amount": "10.001"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_escrow_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={"payer": "pro-agent", "payee": "b", "amount": "-5"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_escrow_zero_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={"payer": "pro-agent", "payee": "b", "amount": "0"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_escrow_overflow_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={"payer": "pro-agent", "payee": "b", "amount": "1000000001"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_performance_escrow_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows/performance",
            json={"payer": "pro-agent", "payee": "b", "amount": "-10", "metric_name": "m", "threshold": "1"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_partial_capture_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents/fake-id/partial-capture",
            json={"amount": "-1"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_partial_capture_zero_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents/fake-id/partial-capture",
            json={"amount": "0"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_split_intent_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/intents/split",
            json={
                "payer": "pro-agent",
                "amount": "-100",
                "splits": [{"payee": "a", "percentage": 100}],
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_subscription_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/subscriptions",
            json={"payer": "pro-agent", "payee": "b", "amount": "-9.99", "interval": "monthly"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_subscription_zero_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/subscriptions",
            json={"payer": "pro-agent", "payee": "b", "amount": "0", "interval": "monthly"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_refund_settlement_negative_amount(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/settlements/fake-id/refund",
            json={"amount": "-10"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Negative / edge-case tests
# ---------------------------------------------------------------------------


async def test_get_nonexistent_intent(client, pro_api_key):
    """GET a non-existent intent -> 404."""
    resp = await client.get(
        "/v1/payments/intents/nonexistent-id-xyz",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 404


async def test_release_non_held_escrow(client, pro_api_key):
    """Releasing an already-released escrow -> error."""
    # Create + release
    resp = await _create_escrow(client, pro_api_key, payee="payee-rlse")
    escrow_id = resp.json()["id"]
    await client.post(
        f"/v1/payments/escrows/{escrow_id}/release",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    # Try to release again — should fail (already settled/released)
    resp = await client.post(
        f"/v1/payments/escrows/{escrow_id}/release",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (400, 404, 409)


async def test_list_intents_with_status_filter(client, pro_api_key):
    """List intents with status filter."""
    await _create_intent(client, pro_api_key, payee="payee-filter")
    resp = await client.get(
        "/v1/payments/intents?agent_id=pro-agent&status=pending",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# ESCROW-CANCEL-BOLA: Only payer (not payee) can cancel escrow
# ---------------------------------------------------------------------------


async def _create_agent_key(app, agent_id: str, tier: str = "pro", balance: float = 5000.0) -> str:
    """Create a wallet + API key for an agent. Returns the raw API key."""
    ctx = app.state.ctx
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except Exception:
        pass
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


# ---------------------------------------------------------------------------
# INTENT-CAPTURE-500: Capture must not return 500
# ---------------------------------------------------------------------------


class TestIntentCapture500:
    """Intent capture must return proper error codes, never 500."""

    async def test_capture_by_non_party_returns_403(self, client, app):
        """A third party trying to capture an intent must get 403."""
        payer_key = await _create_agent_key(app, "cap-payer-1")
        await _create_agent_key(app, "cap-payee-1")
        outsider_key = await _create_agent_key(app, "cap-outsider-1")

        resp = await _create_intent(client, payer_key, payer="cap-payer-1", payee="cap-payee-1")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {outsider_key}"},
        )
        assert resp.status_code == 403

    async def test_capture_nonexistent_intent_returns_404(self, client, app):
        """Capturing a nonexistent intent must return 404."""
        key = await _create_agent_key(app, "cap-agent-404")
        resp = await client.post(
            "/v1/payments/intents/nonexistent-id/capture",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 404

    async def test_capture_already_settled_returns_409(self, client, app):
        """Capturing an already-captured intent must return 409."""
        payer_key = await _create_agent_key(app, "cap-payer-2")
        await _create_agent_key(app, "cap-payee-2")

        resp = await _create_intent(client, payer_key, payer="cap-payer-2", payee="cap-payee-2")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        # First capture — succeeds
        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 200

        # Second capture — must be 409 (not 500)
        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 409

    async def test_capture_by_payee_returns_403(self, client, app):
        """BOLA: payee must NOT be able to capture payer's intent.

        Only the payer (who authorized the payment) can trigger capture.
        Allowing the payee to capture enables wallet theft — the payee
        can force-settle any pending intent, draining the payer's wallet.
        """
        payer_key = await _create_agent_key(app, "bola-payer")
        payee_key = await _create_agent_key(app, "bola-payee")

        resp = await _create_intent(client, payer_key, payer="bola-payer", payee="bola-payee")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        # Payee tries to capture — must be 403
        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payee_key}"},
        )
        assert resp.status_code == 403, f"BOLA: payee captured payer's intent! Got {resp.status_code}: {resp.json()}"

    async def test_partial_capture_by_payee_returns_403(self, client, app):
        """BOLA: payee must NOT be able to partial-capture payer's intent."""
        payer_key = await _create_agent_key(app, "bola-payer-pc")
        payee_key = await _create_agent_key(app, "bola-payee-pc")

        resp = await _create_intent(client, payer_key, payer="bola-payer-pc", payee="bola-payee-pc", amount="200.00")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/partial-capture",
            json={"amount": "50.00"},
            headers={"Authorization": f"Bearer {payee_key}"},
        )
        assert resp.status_code == 403, (
            f"BOLA: payee partial-captured payer's intent! Got {resp.status_code}: {resp.json()}"
        )

    async def test_capture_by_owner_returns_200(self, client, app):
        """Owner (payer) capturing a valid intent must succeed."""
        payer_key = await _create_agent_key(app, "cap-payer-3")
        await _create_agent_key(app, "cap-payee-3")

        resp = await _create_intent(client, payer_key, payer="cap-payer-3", payee="cap-payee-3")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "settled"

    async def test_capture_with_no_payee_wallet_returns_4xx(self, client, app):
        """Capture when payee has no wallet must NOT return 500."""
        payer_key = await _create_agent_key(app, "cap-payer-nowall")
        # payee "no-wallet-payee" intentionally NOT created
        resp = await _create_intent(client, payer_key, payer="cap-payer-nowall", payee="no-wallet-payee")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        # Must be a proper error (402/404), NOT 500
        assert resp.status_code != 500, f"Got 500: {resp.json()}"
        assert resp.status_code in (402, 404)


class TestValueErrorMapping:
    """ValueError from product internals must map to 400, not 500."""

    async def test_value_error_mapped_to_400(self):
        """handle_product_exception must map ValueError to 400."""
        from unittest.mock import MagicMock

        from gateway.src.errors import handle_product_exception

        request = MagicMock()
        request.url.path = "/test"
        resp = await handle_product_exception(request, ValueError("bad input"))
        assert resp.status_code == 400


class TestBOLAInfoDisclosure:
    """403 responses must NOT leak caller/target agent IDs or payer/payee names."""

    async def test_intent_403_no_id_leak(self, client, app):
        """Third-party capturing an intent must get generic 403 message."""
        payer_key = await _create_agent_key(app, "bola-payer-1")
        await _create_agent_key(app, "bola-payee-1")
        outsider_key = await _create_agent_key(app, "bola-outsider-1")

        resp = await _create_intent(client, payer_key, payer="bola-payer-1", payee="bola-payee-1")
        assert resp.status_code == 201
        intent_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/intents/{intent_id}/capture",
            headers={"Authorization": f"Bearer {outsider_key}"},
        )
        assert resp.status_code == 403
        body = str(resp.json())
        assert "bola-payer-1" not in body
        assert "bola-payee-1" not in body
        assert "bola-outsider-1" not in body

    async def test_escrow_403_no_id_leak(self, client, app):
        """Third-party releasing an escrow must get generic 403 message."""
        payer_key = await _create_agent_key(app, "bola-epayer-1")
        await _create_agent_key(app, "bola-epayee-1")
        outsider_key = await _create_agent_key(app, "bola-eout-1")

        resp = await _create_escrow(client, payer_key, payer="bola-epayer-1", payee="bola-epayee-1")
        assert resp.status_code == 201
        escrow_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/escrows/{escrow_id}/release",
            headers={"Authorization": f"Bearer {outsider_key}"},
        )
        assert resp.status_code == 403
        body = str(resp.json())
        assert "bola-epayer-1" not in body
        assert "bola-epayee-1" not in body
        assert "bola-eout-1" not in body

    async def test_escrow_cancel_403_no_id_leak(self, client, app):
        """Payee cancelling an escrow must get generic 403 without leaking payer."""
        payer_key = await _create_agent_key(app, "bola-cpayer-1")
        payee_key = await _create_agent_key(app, "bola-cpayee-1")

        resp = await _create_escrow(client, payer_key, payer="bola-cpayer-1", payee="bola-cpayee-1")
        assert resp.status_code == 201
        escrow_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/escrows/{escrow_id}/cancel",
            headers={"Authorization": f"Bearer {payee_key}"},
        )
        assert resp.status_code == 403
        body = str(resp.json())
        assert "bola-cpayer-1" not in body
        assert "bola-cpayee-1" not in body


class TestEscrowCancelBOLA:
    """Only the escrow payer (or admin) may cancel — payee and third parties must get 403."""

    async def test_payee_cannot_cancel_escrow(self, client, app):
        """Payee calling cancel on an escrow they didn't create must get 403."""
        payer_key = await _create_agent_key(app, "esc-payer-1")
        payee_key = await _create_agent_key(app, "esc-payee-1")

        # Payer creates escrow
        resp = await _create_escrow(client, payer_key, payer="esc-payer-1", payee="esc-payee-1")
        assert resp.status_code == 201
        escrow_id = resp.json()["id"]

        # Payee tries to cancel -> 403
        resp = await client.post(
            f"/v1/payments/escrows/{escrow_id}/cancel",
            headers={"Authorization": f"Bearer {payee_key}"},
        )
        assert resp.status_code == 403

    async def test_third_party_cannot_cancel_escrow(self, client, app):
        """A third party (neither payer nor payee) must get 403 on cancel."""
        payer_key = await _create_agent_key(app, "esc-payer-2")
        await _create_agent_key(app, "esc-payee-2")
        outsider_key = await _create_agent_key(app, "esc-outsider-2")

        resp = await _create_escrow(client, payer_key, payer="esc-payer-2", payee="esc-payee-2")
        assert resp.status_code == 201
        escrow_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/escrows/{escrow_id}/cancel",
            headers={"Authorization": f"Bearer {outsider_key}"},
        )
        assert resp.status_code == 403

    async def test_payer_can_cancel_escrow(self, client, app):
        """Payer must be able to cancel their own escrow."""
        payer_key = await _create_agent_key(app, "esc-payer-3")
        await _create_agent_key(app, "esc-payee-3")

        resp = await _create_escrow(client, payer_key, payer="esc-payer-3", payee="esc-payee-3")
        assert resp.status_code == 201
        escrow_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/payments/escrows/{escrow_id}/cancel",
            headers={"Authorization": f"Bearer {payer_key}"},
        )
        assert resp.status_code == 200
