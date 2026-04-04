"""Tests for P0 #4: X402 nonces hardening.

DB-backed nonce tracking must not fall back to in-memory-only.
"""

from __future__ import annotations

import pytest

from gateway.src.tool_errors import X402ReplayError
from gateway.src.x402 import X402Verifier

pytestmark = pytest.mark.asyncio


class TestX402NoncesHardening:
    """X402 nonce replay protection must be persistent."""

    async def test_duplicate_nonce_rejected(self, app):
        """Nonce used twice should raise X402ReplayError."""
        ctx = app.state.ctx
        db = ctx.tracker.storage.db

        # Create the nonce table
        await db.execute("CREATE TABLE IF NOT EXISTS x402_nonces (nonce TEXT PRIMARY KEY, used_at REAL)")
        await db.commit()

        verifier = X402Verifier(
            merchant_address="0xMerchant",
            facilitator_url="https://x402.org/facilitator",
            supported_networks={"base": "0xUSDC"},
            nonce_db=db,
        )

        # First use should succeed
        await verifier.check_replay_persistent("nonce-abc-123")

        # Second use should fail
        with pytest.raises(X402ReplayError):
            await verifier.check_replay_persistent("nonce-abc-123")

    async def test_nonce_db_none_raises_on_check(self):
        """If nonce_db is None, check_replay_persistent should still prevent
        replays via in-memory set (backward compat), but production must
        always have a DB.
        """
        verifier = X402Verifier(
            merchant_address="0xMerchant",
            facilitator_url="https://x402.org/facilitator",
            supported_networks={"base": "0xUSDC"},
            nonce_db=None,
        )

        # First use succeeds
        await verifier.check_replay_persistent("nonce-no-db")
        # Second use fails via in-memory
        with pytest.raises(X402ReplayError):
            await verifier.check_replay_persistent("nonce-no-db")
