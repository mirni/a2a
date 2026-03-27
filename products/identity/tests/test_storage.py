"""TDD tests for the identity storage layer."""

from __future__ import annotations

import time

import pytest

from products.identity.src.models import (
    AgentIdentity,
    AgentReputation,
    AuditorAttestation,
    MetricCommitment,
    VerifiedClaim,
)


class TestAgentIdentityStorage:
    """Tests for agent identity CRUD."""

    @pytest.mark.asyncio
    async def test_register_and_get_identity(self, storage):
        """Storing an identity should be retrievable by agent_id."""
        identity = AgentIdentity(
            agent_id="bot-1",
            public_key="aa" * 32,
            created_at=time.time(),
            org_id="test-org",
        )
        stored = await storage.store_identity(identity)
        assert stored.agent_id == "bot-1"

        retrieved = await storage.get_identity("bot-1")
        assert retrieved is not None
        assert retrieved.public_key == "aa" * 32
        assert retrieved.org_id == "test-org"

    @pytest.mark.asyncio
    async def test_get_nonexistent_identity_returns_none(self, storage):
        """Getting a non-existent agent should return None."""
        result = await storage.get_identity("no-such-agent")
        assert result is None


class TestMetricCommitmentStorage:
    """Tests for metric commitment storage."""

    @pytest.mark.asyncio
    async def test_store_and_get_commitments(self, storage):
        """Stored commitments should be retrievable by agent_id."""
        now = time.time()
        c1 = MetricCommitment(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            commitment_hash="ab" * 32,
            timestamp=now,
            window_days=30,
        )
        c2 = MetricCommitment(
            agent_id="bot-1",
            metric_name="max_drawdown_30d",
            commitment_hash="cd" * 32,
            timestamp=now,
            window_days=30,
        )
        await storage.store_commitment(c1)
        await storage.store_commitment(c2)

        commitments = await storage.get_commitments("bot-1")
        assert len(commitments) == 2
        metric_names = {c.metric_name for c in commitments}
        assert "sharpe_30d" in metric_names
        assert "max_drawdown_30d" in metric_names

    @pytest.mark.asyncio
    async def test_get_commitments_with_since_filter(self, storage):
        """The since parameter should filter old commitments."""
        old_time = time.time() - 10000
        new_time = time.time()

        c_old = MetricCommitment(
            agent_id="bot-1",
            metric_name="sharpe_30d",
            commitment_hash="11" * 32,
            timestamp=old_time,
        )
        c_new = MetricCommitment(
            agent_id="bot-1",
            metric_name="pnl_30d",
            commitment_hash="22" * 32,
            timestamp=new_time,
        )
        await storage.store_commitment(c_old)
        await storage.store_commitment(c_new)

        # Filter: only since midpoint
        midpoint = old_time + 5000
        results = await storage.get_commitments("bot-1", since=midpoint)
        assert len(results) == 1
        assert results[0].metric_name == "pnl_30d"


class TestAttestationStorage:
    """Tests for auditor attestation storage."""

    @pytest.mark.asyncio
    async def test_store_and_get_attestation(self, storage):
        """Stored attestations should be retrievable by agent_id."""
        now = time.time()
        attestation = AuditorAttestation(
            agent_id="bot-1",
            commitment_hashes=["hash1", "hash2"],
            verified_at=now,
            valid_until=now + 7 * 86400,
            data_source="self_reported",
            signature="sig" * 20,
        )
        row_id = await storage.store_attestation(attestation)
        assert row_id > 0

        attestations = await storage.get_attestations("bot-1")
        assert len(attestations) == 1
        assert attestations[0].commitment_hashes == ["hash1", "hash2"]
        assert attestations[0].data_source == "self_reported"

    @pytest.mark.asyncio
    async def test_expired_attestations_filtered(self, storage):
        """Expired attestations should not appear when valid_only=True."""
        now = time.time()

        # Expired attestation
        expired = AuditorAttestation(
            agent_id="bot-1",
            commitment_hashes=["old_hash"],
            verified_at=now - 20 * 86400,
            valid_until=now - 1,  # Expired 1 second ago
            data_source="self_reported",
            signature="old_sig",
        )
        # Valid attestation
        valid = AuditorAttestation(
            agent_id="bot-1",
            commitment_hashes=["new_hash"],
            verified_at=now,
            valid_until=now + 7 * 86400,
            data_source="exchange_api",
            signature="new_sig",
        )
        await storage.store_attestation(expired)
        await storage.store_attestation(valid)

        # valid_only=True (default)
        results = await storage.get_attestations("bot-1", valid_only=True)
        assert len(results) == 1
        assert results[0].data_source == "exchange_api"

        # valid_only=False
        all_results = await storage.get_attestations("bot-1", valid_only=False)
        assert len(all_results) == 2

    @pytest.mark.asyncio
    async def test_get_attestation_by_id(self, storage):
        """Should retrieve a specific attestation by its row ID."""
        now = time.time()
        attestation = AuditorAttestation(
            agent_id="bot-1",
            commitment_hashes=["h1"],
            verified_at=now,
            valid_until=now + 86400,
            data_source="platform_verified",
            signature="sig123",
        )
        row_id = await storage.store_attestation(attestation)
        result = await storage.get_attestation_by_id(row_id)
        assert result is not None
        assert result.agent_id == "bot-1"


class TestReputationStorage:
    """Tests for agent reputation storage."""

    @pytest.mark.asyncio
    async def test_store_and_get_reputation(self, storage):
        """Stored reputation should be retrievable as the latest record."""
        now = time.time()
        rep = AgentReputation(
            agent_id="bot-1",
            timestamp=now,
            payment_reliability=80.0,
            dispute_rate=10.0,
            transaction_volume_score=50.0,
            composite_score=55.0,
            confidence=0.8,
        )
        row_id = await storage.store_reputation(rep)
        assert row_id > 0

        latest = await storage.get_latest_reputation("bot-1")
        assert latest is not None
        assert latest.payment_reliability == 80.0
        assert latest.composite_score == 55.0
        assert latest.confidence == 0.8

    @pytest.mark.asyncio
    async def test_get_latest_reputation_returns_most_recent(self, storage):
        """When multiple reputation records exist, get_latest should return the newest."""
        now = time.time()
        rep_old = AgentReputation(
            agent_id="bot-1",
            timestamp=now - 1000,
            composite_score=40.0,
        )
        rep_new = AgentReputation(
            agent_id="bot-1",
            timestamp=now,
            composite_score=60.0,
        )
        await storage.store_reputation(rep_old)
        await storage.store_reputation(rep_new)

        latest = await storage.get_latest_reputation("bot-1")
        assert latest is not None
        assert latest.composite_score == 60.0

    @pytest.mark.asyncio
    async def test_get_reputation_nonexistent_agent(self, storage):
        """Getting reputation for a non-existent agent should return None."""
        result = await storage.get_latest_reputation("ghost")
        assert result is None


class TestClaimChainStorage:
    """Tests for claim_chains table storage."""

    @pytest.mark.asyncio
    async def test_store_and_get_claim_chain(self, storage):
        """Storing a claim chain should be retrievable by agent_id."""
        import json

        leaf_hashes = ["aa" * 32, "bb" * 32, "cc" * 32]
        now = time.time()
        chain_id = await storage.store_claim_chain(
            agent_id="bot-1",
            merkle_root="dd" * 32,
            leaf_hashes=leaf_hashes,
            period_start=now - 86400 * 180,
            period_end=now,
        )
        assert chain_id > 0

        chains = await storage.get_claim_chains("bot-1")
        assert len(chains) == 1
        chain = chains[0]
        assert chain["agent_id"] == "bot-1"
        assert chain["merkle_root"] == "dd" * 32
        assert json.loads(chain["leaf_hashes"]) == leaf_hashes
        assert chain["chain_length"] == 3
        assert chain["period_start"] == pytest.approx(now - 86400 * 180, abs=1.0)
        assert chain["period_end"] == pytest.approx(now, abs=1.0)

    @pytest.mark.asyncio
    async def test_get_claim_chains_respects_limit(self, storage):
        """get_claim_chains should respect the limit parameter."""
        now = time.time()
        for i in range(5):
            await storage.store_claim_chain(
                agent_id="bot-limit",
                merkle_root=f"{i:02x}" * 32,
                leaf_hashes=[f"{i:02x}" * 32],
                period_start=now - 1000 + i,
                period_end=now + i,
            )

        chains = await storage.get_claim_chains("bot-limit", limit=3)
        assert len(chains) == 3

    @pytest.mark.asyncio
    async def test_get_claim_chains_returns_newest_first(self, storage):
        """Chains should be ordered by created_at descending."""
        now = time.time()
        await storage.store_claim_chain(
            agent_id="bot-order",
            merkle_root="aa" * 32,
            leaf_hashes=["aa" * 32],
            period_start=now - 200,
            period_end=now - 100,
        )
        await storage.store_claim_chain(
            agent_id="bot-order",
            merkle_root="bb" * 32,
            leaf_hashes=["bb" * 32],
            period_start=now - 100,
            period_end=now,
        )

        chains = await storage.get_claim_chains("bot-order")
        assert len(chains) == 2
        # Most recent first (higher created_at)
        assert chains[0]["merkle_root"] == "bb" * 32
        assert chains[1]["merkle_root"] == "aa" * 32

    @pytest.mark.asyncio
    async def test_get_claim_chains_empty(self, storage):
        """Should return empty list for agent with no chains."""
        chains = await storage.get_claim_chains("ghost-agent")
        assert chains == []
