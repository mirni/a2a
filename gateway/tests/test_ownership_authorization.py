"""Tests for ownership authorization on financial operations.

Verifies that agents cannot perform financial operations on resources
they do not own. Tools like capture_intent, release_escrow, cancel_escrow,
and refund_intent accept only resource IDs, so ownership must be verified
by looking up the resource and checking the caller's involvement.

These are negative tests -- each must return 403 when a non-owner tries
to perform the operation.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 5000.0) -> str:
    """Create a wallet + API key for an agent. Returns the raw API key."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _create_admin_agent(app, agent_id: str = "admin-owner") -> str:
    """Create an admin-tier agent. Returns the raw API key."""
    import hashlib
    import secrets

    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=10000.0, signup_bonus=False)

    raw_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(
        key_hash=key_hash,
        agent_id=agent_id,
        tier="admin",
    )
    return raw_key


async def _execute(client, tool: str, params: dict, api_key: str):
    """Helper to call /v1/execute."""
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {api_key}"},
    )


# ---------------------------------------------------------------------------
# 1. Withdraw -- agent A cannot withdraw from agent B's wallet
# ---------------------------------------------------------------------------


class TestWithdrawOwnership:
    """Withdraw must enforce that agent_id matches the caller."""

    async def test_agent_cannot_withdraw_from_other_wallet(self, client, app):
        """403: agent A cannot withdraw from agent B's wallet."""
        key_alice = await _create_agent(app, "alice-w")
        await _create_agent(app, "bob-w")

        resp = await _execute(
            client,
            "withdraw",
            {
                "agent_id": "bob-w",
                "amount": 10,
            },
            key_alice,
        )

        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")

    async def test_agent_can_withdraw_from_own_wallet(self, client, app):
        """200: agent can withdraw from own wallet."""
        key_alice = await _create_agent(app, "alice-w2")

        resp = await _execute(
            client,
            "withdraw",
            {
                "agent_id": "alice-w2",
                "amount": 10,
            },
            key_alice,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Deposit -- agent A cannot deposit to agent B's wallet
# ---------------------------------------------------------------------------


class TestDepositOwnership:
    """Deposit must enforce that agent_id matches the caller."""

    async def test_agent_cannot_deposit_to_other_wallet(self, client, app):
        """403: agent A cannot deposit into agent B's wallet."""
        key_alice = await _create_agent(app, "alice-d")
        await _create_agent(app, "bob-d")

        resp = await _execute(
            client,
            "deposit",
            {
                "agent_id": "bob-d",
                "amount": 100,
            },
            key_alice,
        )

        assert resp.status_code == 403
        assert resp.json()["type"].endswith("/forbidden")


# ---------------------------------------------------------------------------
# 3. Capture Intent -- agent A cannot capture agent B's intent
# ---------------------------------------------------------------------------


class TestCaptureIntentOwnership:
    """capture_intent must verify that the caller is the payer or payee."""

    async def test_non_party_cannot_capture_intent(self, client, app):
        """403: unrelated agent cannot capture an intent between two others."""
        key_alice = await _create_agent(app, "alice-ci")
        await _create_agent(app, "bob-ci")
        key_eve = await _create_agent(app, "eve-ci")

        # Alice creates an intent where Alice pays Bob
        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-ci",
                "payee": "bob-ci",
                "amount": 10.0,
                "description": "test intent",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        # Eve (unrelated) tries to capture it
        resp = await _execute(
            client,
            "capture_intent",
            {
                "intent_id": intent_id,
            },
            key_eve,
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.json()}"

    async def test_payer_can_capture_own_intent(self, client, app):
        """200: payer can capture their own intent."""
        key_alice = await _create_agent(app, "alice-ci2")
        await _create_agent(app, "bob-ci2")

        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-ci2",
                "payee": "bob-ci2",
                "amount": 10.0,
                "description": "test intent",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "capture_intent",
            {
                "intent_id": intent_id,
            },
            key_alice,
        )

        assert resp.status_code == 200

    async def test_payee_can_capture_intent(self, client, app):
        """200: payee can capture an intent addressed to them."""
        key_alice = await _create_agent(app, "alice-ci3")
        key_bob = await _create_agent(app, "bob-ci3")

        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-ci3",
                "payee": "bob-ci3",
                "amount": 10.0,
                "description": "test intent",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "capture_intent",
            {
                "intent_id": intent_id,
            },
            key_bob,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. Release Escrow -- agent A cannot release agent B's escrow
#    Note: create_escrow and release_escrow require pro tier.
# ---------------------------------------------------------------------------


class TestReleaseEscrowOwnership:
    """release_escrow must verify that the caller is the payer."""

    async def test_non_party_cannot_release_escrow(self, client, app):
        """403: unrelated agent cannot release an escrow between two others."""
        key_alice = await _create_agent(app, "alice-re", tier="pro")
        await _create_agent(app, "bob-re", tier="pro")
        key_eve = await _create_agent(app, "eve-re", tier="pro")

        # Alice creates an escrow (Alice pays Bob)
        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-re",
                "payee": "bob-re",
                "amount": 50.0,
                "description": "test escrow",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        # Eve tries to release it
        resp = await _execute(
            client,
            "release_escrow",
            {
                "escrow_id": escrow_id,
            },
            key_eve,
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.json()}"

    async def test_payer_can_release_escrow(self, client, app):
        """200: payer can release their own escrow."""
        key_alice = await _create_agent(app, "alice-re2", tier="pro")
        await _create_agent(app, "bob-re2", tier="pro")

        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-re2",
                "payee": "bob-re2",
                "amount": 50.0,
                "description": "test escrow",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "release_escrow",
            {
                "escrow_id": escrow_id,
            },
            key_alice,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 5. Cancel Escrow -- agent A cannot cancel agent B's escrow
#    Note: create_escrow requires pro tier; cancel_escrow is free tier.
# ---------------------------------------------------------------------------


class TestCancelEscrowOwnership:
    """cancel_escrow must verify that the caller is the payer."""

    async def test_non_party_cannot_cancel_escrow(self, client, app):
        """403: unrelated agent cannot cancel an escrow between two others."""
        key_alice = await _create_agent(app, "alice-ce", tier="pro")
        await _create_agent(app, "bob-ce", tier="pro")
        key_eve = await _create_agent(app, "eve-ce")

        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-ce",
                "payee": "bob-ce",
                "amount": 50.0,
                "description": "test escrow",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        # Eve tries to cancel it
        resp = await _execute(
            client,
            "cancel_escrow",
            {
                "escrow_id": escrow_id,
            },
            key_eve,
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.json()}"

    async def test_payer_can_cancel_escrow(self, client, app):
        """200: payer can cancel their own escrow."""
        key_alice = await _create_agent(app, "alice-ce2", tier="pro")
        await _create_agent(app, "bob-ce2", tier="pro")

        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-ce2",
                "payee": "bob-ce2",
                "amount": 50.0,
                "description": "test escrow",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "cancel_escrow",
            {
                "escrow_id": escrow_id,
            },
            key_alice,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. Refund Intent -- agent A cannot refund agent B's intent
# ---------------------------------------------------------------------------


class TestRefundIntentOwnership:
    """refund_intent must verify that the caller is involved in the intent."""

    async def test_non_party_cannot_refund_intent(self, client, app):
        """403: unrelated agent cannot refund an intent between two others."""
        key_alice = await _create_agent(app, "alice-ri")
        await _create_agent(app, "bob-ri")
        key_eve = await _create_agent(app, "eve-ri")

        # Alice creates an intent (Alice pays Bob)
        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-ri",
                "payee": "bob-ri",
                "amount": 10.0,
                "description": "refund test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        # Eve tries to refund it
        resp = await _execute(
            client,
            "refund_intent",
            {
                "intent_id": intent_id,
            },
            key_eve,
        )

        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.json()}"

    async def test_payer_can_refund_own_intent(self, client, app):
        """200: payer can refund their own intent (void pending)."""
        key_alice = await _create_agent(app, "alice-ri2")
        await _create_agent(app, "bob-ri2")

        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-ri2",
                "payee": "bob-ri2",
                "amount": 10.0,
                "description": "refund test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "refund_intent",
            {
                "intent_id": intent_id,
            },
            key_alice,
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 7. Admin bypass on resource-based ownership checks
# ---------------------------------------------------------------------------


class TestAdminBypassResourceOwnership:
    """Admin agents should bypass all ownership checks, including resource-based ones."""

    async def test_admin_can_capture_any_intent(self, client, app):
        """200: admin can capture an intent they are not party to."""
        key_alice = await _create_agent(app, "alice-admin-ci")
        await _create_agent(app, "bob-admin-ci")
        admin_key = await _create_admin_agent(app, "admin-ci")

        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-admin-ci",
                "payee": "bob-admin-ci",
                "amount": 10.0,
                "description": "admin capture test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "capture_intent",
            {
                "intent_id": intent_id,
            },
            admin_key,
        )

        assert resp.status_code == 200

    async def test_admin_can_release_any_escrow(self, client, app):
        """200: admin can release an escrow they are not party to."""
        key_alice = await _create_agent(app, "alice-admin-re", tier="pro")
        await _create_agent(app, "bob-admin-re", tier="pro")
        admin_key = await _create_admin_agent(app, "admin-re")

        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-admin-re",
                "payee": "bob-admin-re",
                "amount": 50.0,
                "description": "admin release test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "release_escrow",
            {
                "escrow_id": escrow_id,
            },
            admin_key,
        )

        assert resp.status_code == 200

    async def test_admin_can_cancel_any_escrow(self, client, app):
        """200: admin can cancel an escrow they are not party to."""
        key_alice = await _create_agent(app, "alice-admin-ce", tier="pro")
        await _create_agent(app, "bob-admin-ce", tier="pro")
        admin_key = await _create_admin_agent(app, "admin-ce")

        create_resp = await _execute(
            client,
            "create_escrow",
            {
                "payer": "alice-admin-ce",
                "payee": "bob-admin-ce",
                "amount": 50.0,
                "description": "admin cancel test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200, f"create_escrow failed: {create_resp.json()}"
        escrow_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "cancel_escrow",
            {
                "escrow_id": escrow_id,
            },
            admin_key,
        )

        assert resp.status_code == 200

    async def test_admin_can_refund_any_intent(self, client, app):
        """200: admin can refund an intent they are not party to."""
        key_alice = await _create_agent(app, "alice-admin-ri")
        await _create_agent(app, "bob-admin-ri")
        admin_key = await _create_admin_agent(app, "admin-ri")

        create_resp = await _execute(
            client,
            "create_intent",
            {
                "payer": "alice-admin-ri",
                "payee": "bob-admin-ri",
                "amount": 10.0,
                "description": "admin refund test",
            },
            key_alice,
        )
        assert create_resp.status_code == 200
        intent_id = create_resp.json()["id"]

        resp = await _execute(
            client,
            "refund_intent",
            {
                "intent_id": intent_id,
            },
            admin_key,
        )

        assert resp.status_code == 200
