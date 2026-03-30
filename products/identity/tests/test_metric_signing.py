"""Tests for cryptographic signing of metric submissions (PRD 011).

Covers: valid signature, invalid signature, nonce replay, backward compat, nonce TTL,
data_source trust tiers.
"""

from __future__ import annotations

import json
import time

import pytest

from products.identity.src.crypto import AgentCrypto


class TestSignedSubmission:
    @pytest.mark.asyncio
    async def test_valid_signature_sets_agent_signed(self, api):
        """A valid Ed25519 signature over canonical JSON sets data_source to 'agent_signed'."""
        reg = await api.register_agent("signer-bot")
        priv = reg.private_key
        metrics = {"sharpe_30d": 2.35, "pnl_30d": 1500.0}
        nonce = "unique-nonce-001"
        # Canonical JSON: sorted keys, compact separators
        canonical = json.dumps(
            {"metrics": metrics, "nonce": nonce},
            sort_keys=True,
            separators=(",", ":"),
        )
        signature = AgentCrypto.sign(priv, canonical.encode())

        result = await api.submit_metrics(
            agent_id="signer-bot",
            metrics=metrics,
            data_source="self_reported",
            signature=signature,
            nonce=nonce,
        )
        assert result.attestation.data_source == "agent_signed"

    @pytest.mark.asyncio
    async def test_invalid_signature_keeps_self_reported(self, api):
        """An invalid signature keeps data_source as the provided value."""
        await api.register_agent("bad-signer")
        metrics = {"sharpe_30d": 1.0}
        nonce = "nonce-bad-sig"

        result = await api.submit_metrics(
            agent_id="bad-signer",
            metrics=metrics,
            data_source="self_reported",
            signature="deadbeef" * 16,  # invalid sig
            nonce=nonce,
        )
        assert result.attestation.data_source == "self_reported"

    @pytest.mark.asyncio
    async def test_nonce_replay_rejected(self, api):
        """Reusing a nonce within the TTL window must raise ValueError."""
        reg = await api.register_agent("replay-bot")
        priv = reg.private_key
        metrics = {"sharpe_30d": 2.0}
        nonce = "replay-nonce"
        canonical = json.dumps(
            {"metrics": metrics, "nonce": nonce},
            sort_keys=True,
            separators=(",", ":"),
        )
        signature = AgentCrypto.sign(priv, canonical.encode())

        # First submission succeeds
        await api.submit_metrics(
            agent_id="replay-bot",
            metrics=metrics,
            data_source="self_reported",
            signature=signature,
            nonce=nonce,
        )
        # Second submission with same nonce must fail
        with pytest.raises(ValueError, match="[Nn]once.*already used"):
            await api.submit_metrics(
                agent_id="replay-bot",
                metrics=metrics,
                data_source="self_reported",
                signature=signature,
                nonce=nonce,
            )

    @pytest.mark.asyncio
    async def test_missing_signature_backward_compat(self, api):
        """Calling submit_metrics without signature/nonce still works (backward compat)."""
        await api.register_agent("legacy-bot")
        result = await api.submit_metrics(
            agent_id="legacy-bot",
            metrics={"sharpe_30d": 1.5},
            data_source="exchange_api",
        )
        assert result.attestation.data_source == "exchange_api"

    @pytest.mark.asyncio
    async def test_signature_without_nonce_ignored(self, api):
        """If signature is provided but nonce is missing, signature verification is skipped."""
        await api.register_agent("no-nonce-bot")
        result = await api.submit_metrics(
            agent_id="no-nonce-bot",
            metrics={"sharpe_30d": 1.0},
            data_source="self_reported",
            signature="something",
        )
        # Without nonce, signature is ignored, data_source stays as-is
        assert result.attestation.data_source == "self_reported"


class TestNonceStorage:
    @pytest.mark.asyncio
    async def test_store_and_check_nonce(self, storage):
        """Nonce is stored and can be checked."""
        await storage.store_nonce("test-nonce", "bot-1")
        used = await storage.is_nonce_used("test-nonce")
        assert used is True

    @pytest.mark.asyncio
    async def test_unused_nonce_returns_false(self, storage):
        """An unused nonce returns False."""
        used = await storage.is_nonce_used("never-used")
        assert used is False

    @pytest.mark.asyncio
    async def test_cleanup_expired_nonces(self, storage):
        """Expired nonces (older than TTL) are cleaned up."""
        # Store a nonce with a timestamp in the past
        old_time = time.time() - 600  # 10 minutes ago
        await storage.db.execute(
            "INSERT INTO submission_nonces (nonce, agent_id, used_at) VALUES (?, ?, ?)",
            ("old-nonce", "bot-1", old_time),
        )
        await storage.db.commit()
        # Store a fresh nonce
        await storage.store_nonce("fresh-nonce", "bot-1")

        deleted = await storage.cleanup_expired_nonces(ttl_seconds=300)
        assert deleted >= 1

        # Old nonce gone
        assert await storage.is_nonce_used("old-nonce") is False
        # Fresh nonce still there
        assert await storage.is_nonce_used("fresh-nonce") is True


class TestDataSourceTrustTiers:
    def test_trust_tier_weights(self):
        """Verify the trust tier weight mapping is correct."""
        from products.identity.src.api import DATA_SOURCE_WEIGHTS

        assert DATA_SOURCE_WEIGHTS["platform_verified"] == 1.0
        assert DATA_SOURCE_WEIGHTS["exchange_api"] == 0.7
        assert DATA_SOURCE_WEIGHTS["agent_signed"] == 0.5
        assert DATA_SOURCE_WEIGHTS["self_reported"] == 0.4
