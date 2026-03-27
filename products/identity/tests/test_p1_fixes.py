"""TDD tests for P1 data integrity/semantics fixes (TODOs 4-8).

TODO-4: attestation_signature round-trip on verified claims
TODO-5: Rename dispute_rate to data_source_quality
TODO-6: store_identity INSERT with conflict detection
TODO-7: Index on verified_claims(metric_name)
TODO-8: version field on AuditorAttestation
"""

from __future__ import annotations

import time

import pytest
import pytest_asyncio

from products.identity.src.api import IdentityAPI, AgentNotFoundError
from products.identity.src.crypto import AgentCrypto
from products.identity.src.models import (
    AgentIdentity,
    AgentReputation,
    AuditorAttestation,
    VerifiedClaim,
)
from products.identity.src.storage import IdentityStorage


# ---------------------------------------------------------------------------
# TODO-4: attestation_signature round-trip
# ---------------------------------------------------------------------------

class TestAttestationSignatureRoundTrip:
    """Claims retrieved from DB should have attestation_signature populated."""

    @pytest.mark.asyncio
    async def test_claim_has_attestation_signature(self, api):
        """get_verified_claims should populate attestation_signature from joined attestation."""
        await api.register_agent("bot-sig-rt")
        result = await api.submit_metrics("bot-sig-rt", {"sharpe_30d": 2.0})
        expected_sig = result.attestation.signature

        claims = await api.get_verified_claims("bot-sig-rt")
        assert len(claims) == 1
        assert claims[0].attestation_signature == expected_sig
        assert len(claims[0].attestation_signature) > 0

    @pytest.mark.asyncio
    async def test_search_claims_has_attestation_signature(self, api):
        """search_claims results should also have attestation_signature."""
        await api.register_agent("bot-sig-search")
        result = await api.submit_metrics("bot-sig-search", {"sharpe_30d": 3.0})
        expected_sig = result.attestation.signature

        claims = await api.storage.search_claims("sharpe_30d", min_value=2.5)
        assert len(claims) >= 1
        sig_claim = next(c for c in claims if c.agent_id == "bot-sig-search")
        assert sig_claim.attestation_signature == expected_sig


# ---------------------------------------------------------------------------
# TODO-5: Rename dispute_rate to data_source_quality
# ---------------------------------------------------------------------------

class TestReputationFieldRename:
    """AgentReputation should use data_source_quality instead of dispute_rate."""

    def test_reputation_model_has_data_source_quality(self):
        """AgentReputation should have data_source_quality field."""
        rep = AgentReputation(
            agent_id="bot-rep",
            timestamp=time.time(),
            data_source_quality=75.0,
        )
        assert rep.data_source_quality == 75.0

    @pytest.mark.asyncio
    async def test_compute_reputation_uses_data_source_quality(self, api):
        """compute_reputation should populate data_source_quality."""
        await api.register_agent("bot-dsq")
        await api.submit_metrics(
            "bot-dsq", {"sharpe_30d": 2.5}, data_source="platform_verified"
        )
        rep = await api.compute_reputation("bot-dsq")
        assert hasattr(rep, "data_source_quality")
        assert rep.data_source_quality > 0


# ---------------------------------------------------------------------------
# TODO-6: store_identity conflict detection
# ---------------------------------------------------------------------------

class TestIdentityConflictDetection:
    """store_identity should raise on duplicate agent_id."""

    @pytest.mark.asyncio
    async def test_duplicate_agent_raises(self, api):
        """Registering the same agent_id twice should raise AgentAlreadyExistsError."""
        from products.identity.src.api import AgentAlreadyExistsError

        await api.register_agent("bot-dup")
        with pytest.raises(AgentAlreadyExistsError):
            await api.register_agent("bot-dup")

    @pytest.mark.asyncio
    async def test_different_agents_ok(self, api):
        """Different agent_ids should not conflict."""
        await api.register_agent("bot-a")
        await api.register_agent("bot-b")
        a = await api.get_identity("bot-a")
        b = await api.get_identity("bot-b")
        assert a is not None
        assert b is not None


# ---------------------------------------------------------------------------
# TODO-7: Index on verified_claims(metric_name)
# ---------------------------------------------------------------------------

class TestMetricNameIndex:
    """verified_claims should have an index on metric_name for search_claims."""

    @pytest.mark.asyncio
    async def test_metric_name_index_exists(self, storage):
        """The idx_claim_metric index should exist in the database."""
        cursor = await storage.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_claim_metric'"
        )
        row = await cursor.fetchone()
        assert row is not None, "idx_claim_metric index should exist"


# ---------------------------------------------------------------------------
# TODO-8: version field on AuditorAttestation
# ---------------------------------------------------------------------------

class TestAttestationVersion:
    """AuditorAttestation should have a version field."""

    def test_attestation_has_default_version(self):
        """AuditorAttestation should default to version '1.0'."""
        att = AuditorAttestation(
            agent_id="bot",
            commitment_hashes=["h1"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
            signature="sig",
        )
        assert att.version == "1.0"

    def test_attestation_custom_version(self):
        """AuditorAttestation should accept a custom version."""
        att = AuditorAttestation(
            agent_id="bot",
            commitment_hashes=["h1"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
            signature="sig",
            version="2.0",
        )
        assert att.version == "2.0"

    @pytest.mark.asyncio
    async def test_attestation_version_persisted(self, api):
        """Attestation version should be stored and retrieved from DB."""
        await api.register_agent("bot-ver")
        result = await api.submit_metrics("bot-ver", {"sharpe_30d": 1.5})
        assert result.attestation.version == "1.0"

        # Retrieve from storage
        attestations = await api.storage.get_attestations("bot-ver")
        assert len(attestations) == 1
        assert attestations[0].version == "1.0"
