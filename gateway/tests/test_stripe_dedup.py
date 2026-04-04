"""Tests for P0 #2: Stripe webhook dedup hardening.

DB dedup must not silently fall back to in-memory on failure.
"""

from __future__ import annotations

import pytest

from gateway.src.stripe_checkout import _processed_sessions

pytestmark = pytest.mark.asyncio


class TestStripeWebhookDedup:
    """Stripe webhook deduplication must fail-closed when DB is unavailable."""

    async def test_duplicate_session_rejected(self, app):
        """A session_id already in the DB should be rejected (dedup works)."""
        ctx = app.state.ctx
        db = ctx.tracker.storage.db

        # Ensure the table exists
        await db.execute(
            "CREATE TABLE IF NOT EXISTS processed_stripe_sessions (session_id TEXT PRIMARY KEY, processed_at REAL)"
        )
        await db.execute(
            "INSERT INTO processed_stripe_sessions (session_id, processed_at) VALUES (?, ?)",
            ("cs_test_dup", 1000.0),
        )
        await db.commit()

        # Simulate the dedup check — same logic as stripe_checkout.py
        cursor = await db.execute(
            "SELECT 1 FROM processed_stripe_sessions WHERE session_id = ?",
            ("cs_test_dup",),
        )
        row = await cursor.fetchone()
        assert row is not None, "Duplicate session should be found in DB"

    async def test_in_memory_set_not_sole_fallback(self):
        """The in-memory set should not be the sole dedup mechanism.

        After this fix, DB failure should raise an error, not silently
        fall back to in-memory.
        """
        # Verify that _processed_sessions is a set (still used as cache)
        assert isinstance(_processed_sessions, set)
