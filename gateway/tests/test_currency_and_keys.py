"""Tests for multi-currency parameters, API key management, and exchange rate tools.

P1 Issues:
1. Expose currency parameter on payment tools (create_intent, create_escrow, deposit, withdraw, get_balance)
2. Add list_api_keys and revoke_api_key tools
3. Add exchange rate query tools (get_exchange_rate, convert_currency)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Issue 1: Multi-currency parameter on payment tools
# ---------------------------------------------------------------------------


class TestMultiCurrencyPaymentTools:
    """Payment tools should accept an optional currency parameter."""

    async def test_get_balance_with_currency_param(self, client, api_key):
        """get_balance with currency=CREDITS should return the balance."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_balance",
                "params": {"agent_id": "test-agent", "currency": "CREDITS"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "balance" in data

    async def test_get_balance_default_currency(self, client, api_key):
        """get_balance without currency should still work (default CREDITS)."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_balance",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "balance" in data

    async def test_get_balance_with_usd_currency(self, client, api_key):
        """get_balance with currency=USD should return 0.0 for a new wallet."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_balance",
                "params": {"agent_id": "test-agent", "currency": "USD"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance"] == 0.0
        assert data["currency"] == "USD"

    async def test_deposit_with_currency_param(self, client, api_key):
        """deposit with currency=CREDITS should work."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "deposit",
                "params": {
                    "agent_id": "test-agent",
                    "amount": 50.0,
                    "currency": "CREDITS",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "new_balance" in data

    async def test_withdraw_with_currency_param(self, client, api_key):
        """withdraw with currency=CREDITS should work."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "withdraw",
                "params": {
                    "agent_id": "test-agent",
                    "amount": 10.0,
                    "currency": "CREDITS",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "new_balance" in data

    async def test_create_intent_with_currency_param(self, client, app, api_key):
        """create_intent with currency param should pass it through."""
        # Create payee wallet
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-agent", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "test-agent",
                    "payee": "payee-agent",
                    "amount": 10.0,
                    "currency": "CREDITS",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["currency"] == "CREDITS"

    async def test_create_escrow_with_currency_param(self, client, app, pro_api_key):
        """create_escrow with currency param should pass it through."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("escrow-payee", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_escrow",
                "params": {
                    "payer": "pro-agent",
                    "payee": "escrow-payee",
                    "amount": 25.0,
                    "currency": "CREDITS",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["currency"] == "CREDITS"

    async def test_create_intent_currency_in_catalog(self, client, api_key):
        """create_intent should accept currency param without validation error."""
        # Even if the tool call itself fails for other reasons, it should
        # not fail due to 'currency' being an unknown parameter in the schema.
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "test-agent",
                    "payee": "nonexistent",
                    "amount": 5.0,
                    "currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        # Should not be a schema validation error about unknown 'currency' field
        error = data.get("error", {})
        assert (
            "currency" not in str(error.get("message", "")).lower()
            or "unknown" not in str(error.get("message", "")).lower()
        )


# ---------------------------------------------------------------------------
# Issue 2: list_api_keys and revoke_api_key tools
# ---------------------------------------------------------------------------


class TestListApiKeys:
    """Tests for the list_api_keys tool."""

    async def test_list_api_keys_exists_in_registry(self, client, api_key):
        """list_api_keys should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_api_keys",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        # Should not be "unknown_tool"
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_list_api_keys_returns_keys(self, client, api_key):
        """list_api_keys should return keys for the agent."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_api_keys",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        assert len(data["keys"]) >= 1  # at least the key used for auth
        # Should NOT expose full key hashes (security)
        for key_entry in data["keys"]:
            assert "key_hash_prefix" in key_entry
            assert "tier" in key_entry
            assert "created_at" in key_entry
            # Should not expose full key_hash
            assert len(key_entry["key_hash_prefix"]) <= 12

    async def test_list_api_keys_ownership_enforced(self, client, api_key):
        """list_api_keys for a different agent should be forbidden."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_api_keys",
                "params": {"agent_id": "other-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403


class TestRevokeApiKey:
    """Tests for the revoke_api_key tool.

    revoke_api_key requires tier=starter, so we use pro_api_key (pro >= starter).
    """

    async def test_revoke_api_key_exists_in_registry(self, client, pro_api_key):
        """revoke_api_key should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "revoke_api_key",
                "params": {"agent_id": "pro-agent", "key_hash_prefix": "nonexistent"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_revoke_api_key_soft_deletes(self, client, app, pro_api_key):
        """revoke_api_key should soft-delete (revoke) a key by hash prefix."""
        ctx = app.state.ctx
        # Create a second key to revoke
        new_key_info = await ctx.key_manager.create_key("pro-agent", tier="free")
        key_hash = new_key_info["key_hash"]
        key_hash_prefix = key_hash[:8]

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "revoke_api_key",
                "params": {"agent_id": "pro-agent", "key_hash_prefix": key_hash_prefix},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["revoked"] is True

    async def test_revoke_api_key_nonexistent_prefix(self, client, pro_api_key):
        """Revoking a key with a nonexistent prefix should report not found."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "revoke_api_key",
                "params": {"agent_id": "pro-agent", "key_hash_prefix": "zzzzzzzz"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["revoked"] is False

    async def test_revoke_api_key_ownership_enforced(self, client, pro_api_key):
        """revoke_api_key for a different agent should be forbidden."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "revoke_api_key",
                "params": {"agent_id": "other-agent", "key_hash_prefix": "abcd1234"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 403

    async def test_revoke_api_key_allowed_for_free_tier(self, client, api_key):
        """revoke_api_key should be accessible to free tier (moved from starter)."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "revoke_api_key",
                "params": {"agent_id": "test-agent", "key_hash_prefix": "abcd1234"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # free agents should be able to revoke their own keys
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Issue 3: Exchange rate query tools
# ---------------------------------------------------------------------------


class TestGetExchangeRate:
    """Tests for the get_exchange_rate tool."""

    async def test_get_exchange_rate_exists(self, client, api_key):
        """get_exchange_rate should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_exchange_rate",
                "params": {"from_currency": "USD", "to_currency": "CREDITS"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_get_exchange_rate_returns_rate(self, client, app, api_key):
        """get_exchange_rate should return the exchange rate."""
        # Initialize default rates first
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_exchange_rate",
                "params": {"from_currency": "USD", "to_currency": "CREDITS"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "rate" in data
        assert data["from_currency"] == "USD"
        assert data["to_currency"] == "CREDITS"
        assert float(data["rate"]) == 100.0

    async def test_get_exchange_rate_auto_initializes(self, client, api_key):
        """get_exchange_rate should auto-initialize default rates without manual setup.

        Regression test: previously the tool never called initialize_default_rates(),
        causing UnsupportedCurrencyError for all currency pairs on fresh databases.
        """
        # NO manual initialization — the tool itself must seed the rates table.
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_exchange_rate",
                "params": {"from_currency": "USD", "to_currency": "CREDITS"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["rate"]) == 100.0

    async def test_get_exchange_rate_same_currency(self, client, api_key):
        """get_exchange_rate for same currency should return rate=1."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_exchange_rate",
                "params": {"from_currency": "CREDITS", "to_currency": "CREDITS"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert float(data["rate"]) == 1.0


class TestConvertCurrency:
    """Tests for the convert_currency tool."""

    async def test_convert_currency_exists(self, client, api_key):
        """convert_currency should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "convert_currency",
                "params": {
                    "agent_id": "test-agent",
                    "amount": 10.0,
                    "from_currency": "CREDITS",
                    "to_currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_convert_currency_auto_initializes(self, client, api_key):
        """convert_currency should auto-initialize rates on fresh databases.

        Regression test: previously the tool never seeded the exchange_rates table.
        """
        # NO manual initialization
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "convert_currency",
                "params": {
                    "agent_id": "test-agent",
                    "amount": 100.0,
                    "from_currency": "CREDITS",
                    "to_currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {data}"
        assert data["from_amount"] == 100.0
        assert data["to_amount"] > 0

    async def test_convert_currency_converts_balance(self, client, app, api_key):
        """convert_currency should withdraw from source and deposit to target."""
        ctx = app.state.ctx
        from billing_src.exchange import ExchangeRateService

        exchange_svc = ExchangeRateService(storage=ctx.tracker.storage)
        await exchange_svc.initialize_default_rates()

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "convert_currency",
                "params": {
                    "agent_id": "test-agent",
                    "amount": 100.0,
                    "from_currency": "CREDITS",
                    "to_currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {data}"
        assert data["from_amount"] == 100.0
        assert data["from_currency"] == "CREDITS"
        assert data["to_currency"] == "USD"
        assert data["to_amount"] > 0

    async def test_convert_currency_ownership_enforced(self, client, api_key):
        """convert_currency for a different agent should be forbidden."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "convert_currency",
                "params": {
                    "agent_id": "other-agent",
                    "amount": 10.0,
                    "from_currency": "CREDITS",
                    "to_currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403
