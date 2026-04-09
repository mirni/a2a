"""Regression tests for external audit findings (v1.1.2).

MEDIUM #1: Long agent_id in POST body bypasses 128-char middleware check.
MEDIUM #2: String amount causes 500 instead of 422.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

LONG_AGENT_ID = "a" * 129


class TestAgentIdBodyMaxLength:
    """MEDIUM #1: agent_id/payer/payee in request bodies must enforce max_length=128."""

    # --- identity.py ---

    async def test_register_agent_long_agent_id(self, client, api_key):
        resp = await client.post(
            "/v1/identity/agents",
            json={"agent_id": LONG_AGENT_ID},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_add_member_long_agent_id(self, client, pro_api_key):
        resp = await client.post(
            "/v1/identity/orgs/org-123/members",
            json={"agent_id": LONG_AGENT_ID, "role": "member"},
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_ingest_metrics_long_agent_id(self, client, api_key):
        resp = await client.post(
            "/v1/identity/metrics/ingest",
            json={"agent_id": LONG_AGENT_ID, "metrics": {"uptime": 0.99}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    # --- billing.py ---

    async def test_create_wallet_long_agent_id(self, client, api_key):
        resp = await client.post(
            "/v1/billing/wallets",
            json={"agent_id": LONG_AGENT_ID},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    # --- payments.py ---

    async def test_create_intent_long_payer(self, client, api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": LONG_AGENT_ID,
                "payee": "agent-bob",
                "amount": "10.00",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_intent_long_payee(self, client, api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "agent-alice",
                "payee": LONG_AGENT_ID,
                "amount": "10.00",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_escrow_long_payer(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={
                "payer": LONG_AGENT_ID,
                "payee": "agent-bob",
                "amount": "50.00",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_create_escrow_long_payee(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={
                "payer": "agent-alice",
                "payee": LONG_AGENT_ID,
                "amount": "50.00",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422

    async def test_128_char_agent_id_accepted(self, client, api_key):
        """Exactly 128 chars should pass validation (may fail ownership check later)."""
        exact_id = "b" * 128
        resp = await client.post(
            "/v1/billing/wallets",
            json={"agent_id": exact_id},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should NOT be 422 — 403 is expected (ownership check failure)
        assert resp.status_code != 422


class TestStringAmountRegression:
    """MEDIUM #2: String amount should return 422, not 500."""

    async def test_string_amount_intent_returns_422(self, client, api_key):
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "test-agent",
                "payee": "agent-bob",
                "amount": "not_a_number",
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 422

    async def test_string_amount_escrow_returns_422(self, client, pro_api_key):
        resp = await client.post(
            "/v1/payments/escrows",
            json={
                "payer": "pro-agent",
                "payee": "agent-bob",
                "amount": "not_a_number",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 422
