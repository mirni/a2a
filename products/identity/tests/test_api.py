"""TDD tests for the IdentityAPI high-level operations."""

from __future__ import annotations

import pytest

from products.identity.src.api import AgentNotFoundError, IdentityAPI, InvalidMetricError
from products.identity.src.crypto import AgentCrypto


class TestRegisterAgent:
    """Tests for agent registration."""

    @pytest.mark.asyncio
    async def test_register_agent_auto_generates_keypair(self, api):
        """register_agent without a public_key should auto-generate one."""
        identity = await api.register_agent("bot-auto")
        assert identity.agent_id == "bot-auto"
        assert len(identity.public_key) == 64  # 32 bytes hex
        bytes.fromhex(identity.public_key)  # Valid hex

    @pytest.mark.asyncio
    async def test_register_agent_with_provided_key(self, api):
        """register_agent with an explicit public_key should store it."""
        _priv, pub = AgentCrypto.generate_keypair()
        identity = await api.register_agent("bot-explicit", public_key=pub)
        assert identity.public_key == pub

    @pytest.mark.asyncio
    async def test_get_identity_after_register(self, api):
        """get_identity should return the registered identity."""
        await api.register_agent("bot-lookup")
        identity = await api.get_identity("bot-lookup")
        assert identity is not None
        assert identity.agent_id == "bot-lookup"

    @pytest.mark.asyncio
    async def test_get_identity_nonexistent(self, api):
        """get_identity for a non-existent agent returns None."""
        result = await api.get_identity("ghost")
        assert result is None


class TestVerifyAgent:
    """Tests for agent signature verification."""

    @pytest.mark.asyncio
    async def test_verify_agent_signature(self, api):
        """verify_agent should return True for a valid signature from the registered agent."""
        priv, pub = AgentCrypto.generate_keypair()
        await api.register_agent("signer", public_key=pub)

        message = b"prove identity"
        sig = AgentCrypto.sign(priv, message)
        assert await api.verify_agent("signer", message, sig) is True

    @pytest.mark.asyncio
    async def test_verify_agent_bad_signature(self, api):
        """verify_agent should return False for an invalid signature."""
        _priv, pub = AgentCrypto.generate_keypair()
        await api.register_agent("signer2", public_key=pub)

        # Sign with a different key
        other_priv, _ = AgentCrypto.generate_keypair()
        sig = AgentCrypto.sign(other_priv, b"prove identity")
        assert await api.verify_agent("signer2", b"prove identity", sig) is False

    @pytest.mark.asyncio
    async def test_verify_agent_not_found(self, api):
        """verify_agent should raise AgentNotFoundError for unknown agent."""
        with pytest.raises(AgentNotFoundError):
            await api.verify_agent("ghost", b"msg", "00" * 64)


class TestSubmitMetrics:
    """Tests for metric submission and attestation."""

    @pytest.mark.asyncio
    async def test_submit_metrics_creates_attestation(self, api):
        """submit_metrics should create commitments and a signed attestation."""
        await api.register_agent("bot-metrics")

        attestation = await api.submit_metrics(
            "bot-metrics",
            {"sharpe_30d": 2.35, "max_drawdown_30d": 5.2},
        )
        assert attestation.agent_id == "bot-metrics"
        assert len(attestation.commitment_hashes) == 2
        assert attestation.data_source == "self_reported"
        assert len(attestation.signature) > 0

        # Verify the attestation signature is valid
        assert AgentCrypto.verify_attestation(
            api.auditor_public_key,
            attestation.agent_id,
            attestation.commitment_hashes,
            attestation.verified_at,
            attestation.valid_until,
            attestation.data_source,
            attestation.signature,
        )

    @pytest.mark.asyncio
    async def test_submit_metrics_creates_verified_claims(self, api):
        """submit_metrics should also create verified claims."""
        await api.register_agent("bot-claims")
        await api.submit_metrics(
            "bot-claims",
            {"sharpe_30d": 2.0, "p99_latency_ms": 50.0},
        )

        claims = await api.get_verified_claims("bot-claims")
        assert len(claims) == 2
        names = {c.metric_name for c in claims}
        assert "sharpe_30d" in names
        assert "p99_latency_ms" in names

        # Check claim types
        sharpe_claim = next(c for c in claims if c.metric_name == "sharpe_30d")
        assert sharpe_claim.claim_type == "gte"
        assert sharpe_claim.bound_value == 2.0

        latency_claim = next(c for c in claims if c.metric_name == "p99_latency_ms")
        assert latency_claim.claim_type == "lte"
        assert latency_claim.bound_value == 50.0

    @pytest.mark.asyncio
    async def test_submit_metrics_agent_not_found(self, api):
        """submit_metrics should raise AgentNotFoundError for unknown agent."""
        with pytest.raises(AgentNotFoundError):
            await api.submit_metrics("ghost", {"sharpe_30d": 1.0})

    @pytest.mark.asyncio
    async def test_submit_metrics_invalid_metric(self, api):
        """submit_metrics should raise InvalidMetricError for unsupported metric names."""
        await api.register_agent("bot-bad")
        with pytest.raises(InvalidMetricError):
            await api.submit_metrics("bot-bad", {"magic_indicator_99": 42.0})


class TestGetVerifiedClaims:
    """Tests for verified claims retrieval."""

    @pytest.mark.asyncio
    async def test_get_verified_claims(self, api):
        """get_verified_claims should return only non-expired claims."""
        await api.register_agent("bot-vc")
        await api.submit_metrics("bot-vc", {"sharpe_30d": 3.0})

        claims = await api.get_verified_claims("bot-vc")
        assert len(claims) == 1
        assert claims[0].metric_name == "sharpe_30d"

    @pytest.mark.asyncio
    async def test_get_verified_claims_empty(self, api):
        """get_verified_claims should return empty list for agent with no claims."""
        await api.register_agent("bot-no-claims")
        claims = await api.get_verified_claims("bot-no-claims")
        assert claims == []


class TestReputation:
    """Tests for reputation computation."""

    @pytest.mark.asyncio
    async def test_get_reputation_none_initially(self, api):
        """get_reputation should return None if no reputation has been computed."""
        await api.register_agent("bot-norep")
        rep = await api.get_reputation("bot-norep")
        assert rep is None

    @pytest.mark.asyncio
    async def test_compute_reputation(self, api):
        """compute_reputation should create a reputation record from attestation data."""
        await api.register_agent("bot-rep")
        await api.submit_metrics(
            "bot-rep",
            {"sharpe_30d": 2.5, "aum": 100000.0},
            data_source="platform_verified",
        )

        rep = await api.compute_reputation("bot-rep")
        assert rep.agent_id == "bot-rep"
        assert rep.composite_score > 0
        assert rep.confidence > 0

        # Should be stored and retrievable
        stored = await api.get_reputation("bot-rep")
        assert stored is not None
        assert stored.composite_score == rep.composite_score

    @pytest.mark.asyncio
    async def test_compute_reputation_agent_not_found(self, api):
        """compute_reputation should raise AgentNotFoundError for unknown agent."""
        with pytest.raises(AgentNotFoundError):
            await api.compute_reputation("ghost")
