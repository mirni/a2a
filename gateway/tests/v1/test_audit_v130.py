"""Tests for v1.3.0 audit findings (gateway fixes).

Covers:
- P6.7:  /v1/health missing docs_url field
- P4.7:  USDC exchange-rate pairs return 500
- P5.8a: Webhook creation event_types vs events alias
- P4.2.0: Agent registration rejects name/capabilities
"""

from __future__ import annotations

import httpx
import pytest

# ---------------------------------------------------------------------------
# P6.7 — /v1/health must include docs_url
# ---------------------------------------------------------------------------


class TestHealthDocsUrl:
    @pytest.mark.asyncio
    async def test_health_has_docs_url(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "docs_url" in body, f"Missing docs_url in health response: {list(body.keys())}"
        assert body["docs_url"]  # non-empty


# ---------------------------------------------------------------------------
# P4.7 — USDC exchange-rate pairs must not 500
# ---------------------------------------------------------------------------


class TestUSDCExchangeRates:
    @pytest.mark.asyncio
    async def test_usdc_to_usd(self, client: httpx.AsyncClient, api_key: str):
        resp = await client.get(
            "/v1/billing/exchange-rates",
            params={"from_currency": "USDC", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, f"USDC->USD returned {resp.status_code}: {resp.text}"
        body = resp.json()
        assert "rate" in body

    @pytest.mark.asyncio
    async def test_credits_to_usdc(self, client: httpx.AsyncClient, api_key: str):
        resp = await client.get(
            "/v1/billing/exchange-rates",
            params={"from_currency": "CREDITS", "to_currency": "USDC"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, f"CREDITS->USDC returned {resp.status_code}: {resp.text}"

    @pytest.mark.asyncio
    async def test_usdc_to_eth(self, client: httpx.AsyncClient, api_key: str):
        resp = await client.get(
            "/v1/billing/exchange-rates",
            params={"from_currency": "USDC", "to_currency": "ETH"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, f"USDC->ETH returned {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# P5.8a — Webhook creation: accept 'events' as alias for 'event_types'
# ---------------------------------------------------------------------------


class TestWebhookEventsAlias:
    @pytest.mark.asyncio
    async def test_create_webhook_with_events_alias(self, client: httpx.AsyncClient, pro_api_key: str):
        """Sending 'events' instead of 'event_types' should work."""
        resp = await client.post(
            "/v1/infra/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["payment.completed"],
                "secret": "whsec_test123",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 201, f"events alias rejected: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body.get("event_types") == ["payment.completed"]

    @pytest.mark.asyncio
    async def test_create_webhook_with_event_types_still_works(self, client: httpx.AsyncClient, pro_api_key: str):
        """Original 'event_types' field must still work."""
        resp = await client.post(
            "/v1/infra/webhooks",
            json={
                "url": "https://example.com/hook2",
                "event_types": ["payment.completed"],
                "secret": "whsec_test456",
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 201, f"event_types rejected: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# P4.2.0 — Agent registration should accept name and capabilities
# ---------------------------------------------------------------------------


class TestAgentRegistrationFields:
    @pytest.mark.asyncio
    async def test_register_with_name_and_capabilities(self, client: httpx.AsyncClient, admin_api_key: str):
        """Sending name + capabilities should not be rejected as extra fields."""
        resp = await client.post(
            "/v1/identity/agents",
            json={
                "agent_id": "audit-web3-test-agent",
                "name": "Web3 Test Agent",
                "capabilities": ["payments", "defi"],
            },
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code != 422, f"name/capabilities rejected: {resp.text}"
        assert resp.status_code in (200, 201, 409), f"Unexpected status: {resp.status_code} {resp.text}"

    @pytest.mark.asyncio
    async def test_register_without_name_still_works(self, client: httpx.AsyncClient, admin_api_key: str):
        """Original minimal payload must still work."""
        resp = await client.post(
            "/v1/identity/agents",
            json={"agent_id": "audit-minimal-agent"},
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code in (200, 201, 409), f"Unexpected status: {resp.status_code} {resp.text}"
