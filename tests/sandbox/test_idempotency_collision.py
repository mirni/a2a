"""T-3 sandbox parity: idempotency body-hash collision (P0-4).

Replaying the same Idempotency-Key with a *different* body must
return 409, not silently create a duplicate payment intent.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


class TestSandboxIdempotencyCollision:
    async def test_same_body_replays_same_response(self, sandbox_client, pro_key):
        key = f"sandbox-audit-{uuid.uuid4()}"
        body = {"amount": "0.01", "currency": "USD", "destination_agent_id": "sandbox-sink"}

        first = await sandbox_client.post(
            "/v1/payments/intents",
            json=body,
            headers={
                "Authorization": f"Bearer {pro_key}",
                "Idempotency-Key": key,
            },
        )
        # First call may succeed (200/201) or fail (402 etc) depending
        # on sandbox wallet state — we don't care, only that the
        # SECOND call returns the same status.
        second = await sandbox_client.post(
            "/v1/payments/intents",
            json=body,
            headers={
                "Authorization": f"Bearer {pro_key}",
                "Idempotency-Key": key,
            },
        )
        assert second.status_code == first.status_code, (
            f"idempotent replay changed status: first={first.status_code}, second={second.status_code}"
        )

    async def test_different_body_returns_409(self, sandbox_client, admin_key):
        # Uses admin_key (enterprise tier, 999,999 credit balance) rather
        # than pro_key because the pro-tier audit wallet is intentionally
        # low-balance and returns 402 before reaching the idempotency
        # check. Admin bypasses balance so we actually exercise the
        # body-hash collision path (P0-4). The *behaviour* we're
        # verifying is gateway-wide and tier-independent.
        key = f"sandbox-audit-{uuid.uuid4()}"

        first = await sandbox_client.post(
            "/v1/payments/intents",
            json={"amount": "0.01", "currency": "USD", "destination_agent_id": "sink-a"},
            headers={
                "Authorization": f"Bearer {admin_key}",
                "Idempotency-Key": key,
            },
        )
        # Ignore first's status — only the collision matters.
        _ = first

        collision = await sandbox_client.post(
            "/v1/payments/intents",
            json={"amount": "99.99", "currency": "USD", "destination_agent_id": "sink-b"},
            headers={
                "Authorization": f"Bearer {admin_key}",
                "Idempotency-Key": key,
            },
        )
        assert collision.status_code == 409, f"idempotency collision should return 409, got {collision.status_code}"
