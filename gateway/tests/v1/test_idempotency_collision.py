"""v1.2.4 audit P0-4: idempotency body-hash validation.

Financial mutations under ``/v1/payments/*`` must enforce strict
idempotency semantics: when a caller replays ``Idempotency-Key: X``:

* Same body → return the original response (exactly once).
* Different body → 409 ``idempotency_key_reused`` with the stored
  body-hash prefix so the caller can diff.

This test file drives the route-level idempotency dep at
``gateway/src/deps/idempotency.py``.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def _create_funded_pair(app, payer, payee, payer_balance=500.0):
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(payer, initial_balance=payer_balance, signup_bonus=False)
    await ctx.tracker.wallet.create(payee, initial_balance=0.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(payer, tier="pro")
    return key_info["key"]


class TestIdempotencyBodyHashCollision:
    """Route-level idempotency must detect body-hash collisions and
    return 409 instead of silently creating a second mutation.
    """

    async def test_replay_same_body_returns_same_response(self, client, app):
        payer_key = await _create_funded_pair(app, "idem-payer-1", "idem-payee-1")
        body = {
            "payer": "idem-payer-1",
            "payee": "idem-payee-1",
            "amount": "5.00",
            "currency": "CREDITS",
            "description": "idem collision test",
        }
        headers = {
            "Authorization": f"Bearer {payer_key}",
            "Idempotency-Key": "idem-test-replay-same-1",
        }
        r1 = await client.post("/v1/payments/intents", headers=headers, json=body)
        assert r1.status_code in (200, 201), r1.text
        body1 = r1.json()

        r2 = await client.post("/v1/payments/intents", headers=headers, json=body)
        assert r2.status_code in (200, 201), r2.text
        body2 = r2.json()
        assert body1.get("id") == body2.get("id"), (
            f"same key + same body must return same intent_id: {body1} vs {body2}"
        )

    async def test_replay_different_body_returns_409(self, client, app):
        payer_key = await _create_funded_pair(app, "idem-payer-2", "idem-payee-2")
        base = {
            "payer": "idem-payer-2",
            "payee": "idem-payee-2",
            "currency": "CREDITS",
            "description": "idem collision test",
        }
        headers = {
            "Authorization": f"Bearer {payer_key}",
            "Idempotency-Key": "idem-test-collision-1",
        }
        r1 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={**base, "amount": "5.00"},
        )
        assert r1.status_code in (200, 201), r1.text

        r2 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={**base, "amount": "6.00"},  # different body → collision
        )
        assert r2.status_code == 409, r2.text
        body = r2.json()
        detail = str(body).lower()
        assert "idempotency" in detail
        # RFC 9457: must be parseable problem+json
        assert body.get("status") == 409

    async def test_replay_different_description_returns_409(self, client, app):
        payer_key = await _create_funded_pair(app, "idem-payer-3", "idem-payee-3")
        base = {
            "payer": "idem-payer-3",
            "payee": "idem-payee-3",
            "amount": "5.00",
            "currency": "CREDITS",
        }
        headers = {
            "Authorization": f"Bearer {payer_key}",
            "Idempotency-Key": "idem-test-collision-desc",
        }
        r1 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={**base, "description": "first call"},
        )
        assert r1.status_code in (200, 201), r1.text

        r2 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={**base, "description": "second call"},
        )
        assert r2.status_code == 409

    async def test_no_idempotency_key_does_not_collide(self, client, app):
        """Without an Idempotency-Key header, each request is distinct."""
        payer_key = await _create_funded_pair(app, "idem-payer-4", "idem-payee-4")
        body = {
            "payer": "idem-payer-4",
            "payee": "idem-payee-4",
            "amount": "5.00",
            "currency": "CREDITS",
            "description": "no-idem",
        }
        headers = {"Authorization": f"Bearer {payer_key}"}
        r1 = await client.post("/v1/payments/intents", headers=headers, json=body)
        r2 = await client.post("/v1/payments/intents", headers=headers, json=body)
        assert r1.status_code in (200, 201)
        assert r2.status_code in (200, 201)
        # Without an idempotency key, each request must produce a
        # distinct intent id.
        assert r1.json().get("id") != r2.json().get("id")

    async def test_body_field_idempotency_key_different_body_returns_409(self, client, app):
        """When the idempotency key is sent in the JSON body field (not the
        HTTP header), different-body collisions must still return 409."""
        payer_key = await _create_funded_pair(app, "idem-payer-6", "idem-payee-6")
        idem_key = "idem-body-field-test-1"
        headers = {"Authorization": f"Bearer {payer_key}"}

        r1 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={
                "payer": "idem-payer-6",
                "payee": "idem-payee-6",
                "amount": "5.00",
                "currency": "CREDITS",
                "idempotency_key": idem_key,
            },
        )
        assert r1.status_code in (200, 201), r1.text

        r2 = await client.post(
            "/v1/payments/intents",
            headers=headers,
            json={
                "payer": "idem-payer-6",
                "payee": "idem-payee-6",
                "amount": "9.00",  # different amount
                "currency": "CREDITS",
                "idempotency_key": idem_key,
            },
        )
        assert r2.status_code == 409, f"expected 409, got {r2.status_code}: {r2.text}"

    async def test_parallel_replay_exactly_one_succeeds(self, client, app):
        """Fire 20 parallel requests with same key + different bodies.

        Exactly one must win; the rest must get 409. This catches the
        check-then-insert race class of bug the plan calls out.
        """
        payer_key = await _create_funded_pair(app, "idem-payer-5", "idem-payee-5", payer_balance=5000.0)
        headers_base = {"Authorization": f"Bearer {payer_key}"}
        key = "idem-race-key"

        async def _one(amount_cents: int):
            return await client.post(
                "/v1/payments/intents",
                headers={**headers_base, "Idempotency-Key": key},
                json={
                    "payer": "idem-payer-5",
                    "payee": "idem-payee-5",
                    "amount": f"{amount_cents / 100:.2f}",
                    "currency": "CREDITS",
                    "description": f"race {amount_cents}",
                },
            )

        responses = await asyncio.gather(*[_one(100 + i) for i in range(20)])
        successes = [r for r in responses if r.status_code in (200, 201)]
        conflicts = [r for r in responses if r.status_code == 409]
        assert len(successes) == 1, (
            f"exactly one request must succeed, got {len(successes)} (statuses: {[r.status_code for r in responses]})"
        )
        assert len(conflicts) == 19, (
            f"remaining 19 must all return 409, got {len(conflicts)} conflicts "
            f"(statuses: {[r.status_code for r in responses]})"
        )
