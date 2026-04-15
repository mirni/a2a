"""F5 audit v1.4.4: Per-currency decimal precision validation.

Ensures that deposit/withdraw amounts are validated against the
maximum decimal places allowed for each currency.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_deposit_usd_2dp_ok(client, api_key):
    """USD with 2 decimal places should be accepted."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "1.99", "currency": "USD"},
    )
    # Should not fail validation (may fail for other reasons like balance)
    assert resp.status_code != 422


async def test_deposit_usd_6dp_rejected(client, api_key):
    """USD with 6 decimal places should be rejected (max 2)."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "1.234567", "currency": "USD"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "decimal" in str(body).lower()


async def test_deposit_btc_8dp_ok(client, api_key):
    """BTC with 8 decimal places (1 satoshi) should be accepted."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "0.00000001", "currency": "BTC"},
    )
    assert resp.status_code != 422


async def test_deposit_btc_9dp_rejected(client, api_key):
    """BTC with 9 decimal places should be rejected (max 8)."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "0.000000001", "currency": "BTC"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "decimal" in str(body).lower()


async def test_deposit_usdc_6dp_ok(client, api_key):
    """USDC with 6 decimal places should be accepted."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "1.123456", "currency": "USDC"},
    )
    assert resp.status_code != 422


async def test_deposit_usdc_7dp_rejected(client, api_key):
    """USDC with 7 decimal places should be rejected (max 6)."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "1.1234567", "currency": "USDC"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "decimal" in str(body).lower()


async def test_withdraw_eur_3dp_rejected(client, api_key):
    """EUR with 3 decimal places should be rejected (max 2)."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/withdraw",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "1.123", "currency": "EUR"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "decimal" in str(body).lower()


async def test_deposit_credits_2dp_ok(client, api_key):
    """CREDITS with 2 decimal places should be accepted."""
    resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"amount": "99.99", "currency": "CREDITS"},
    )
    assert resp.status_code != 422


# ---------------------------------------------------------------------------
# Payment intent decimal precision (v1.4.6 audit regression)
# ---------------------------------------------------------------------------


async def test_intent_credits_6dp_rejected(client, pro_api_key):
    """CREDITS intent with 6dp must be rejected (max 2). v1.4.6 regression."""
    resp = await client.post(
        "/v1/payments/intents",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={"payer": "pro-agent", "payee": "test-agent", "amount": "1.234567", "currency": "CREDITS"},
    )
    assert resp.status_code == 422
    assert "decimal" in str(resp.json()).lower()


async def test_intent_usd_6dp_rejected(client, pro_api_key):
    """USD intent with 6dp must be rejected (max 2)."""
    resp = await client.post(
        "/v1/payments/intents",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={"payer": "pro-agent", "payee": "test-agent", "amount": "1.234567", "currency": "USD"},
    )
    assert resp.status_code == 422
    assert "decimal" in str(resp.json()).lower()


async def test_intent_btc_8dp_ok(client, pro_api_key):
    """BTC intent with 8dp should be accepted."""
    resp = await client.post(
        "/v1/payments/intents",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={"payer": "pro-agent", "payee": "test-agent", "amount": "0.00000001", "currency": "BTC"},
    )
    assert resp.status_code != 422


async def test_intent_btc_9dp_rejected(client, pro_api_key):
    """BTC intent with 9dp must be rejected (max 8)."""
    resp = await client.post(
        "/v1/payments/intents",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={"payer": "pro-agent", "payee": "test-agent", "amount": "0.000000001", "currency": "BTC"},
    )
    assert resp.status_code == 422
    assert "decimal" in str(resp.json()).lower()


async def test_escrow_credits_6dp_rejected(client, pro_api_key):
    """CREDITS escrow with 6dp must be rejected (max 2)."""
    resp = await client.post(
        "/v1/payments/escrows",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={"payer": "pro-agent", "payee": "test-agent", "amount": "1.234567", "currency": "CREDITS"},
    )
    assert resp.status_code == 422
    assert "decimal" in str(resp.json()).lower()


async def test_subscription_credits_6dp_rejected(client, pro_api_key):
    """CREDITS subscription with 6dp must be rejected (max 2)."""
    resp = await client.post(
        "/v1/payments/subscriptions",
        headers={"Authorization": f"Bearer {pro_api_key}"},
        json={
            "payer": "pro-agent",
            "payee": "test-agent",
            "amount": "1.234567",
            "interval": "monthly",
            "currency": "CREDITS",
        },
    )
    assert resp.status_code == 422
    assert "decimal" in str(resp.json()).lower()
