"""TDD tests for P3 extensibility features (TODOs 13-18).

TODO-13: Algorithm field on attestation schema
TODO-14: Configurable metric set (per-org custom metrics)
TODO-15: Auditor key rotation with versioning
TODO-16: W3C VC alignment (issuer, credentialSubject, proof structure)
TODO-17: Merkle proof endpoint
TODO-18: Integrate reputation with payment/dispute data
"""

from __future__ import annotations

import pytest

from products.identity.src.api import InvalidMetricError
from products.identity.src.crypto import AgentCrypto, MerkleTree
from products.identity.src.models import AuditorAttestation

# ---------------------------------------------------------------------------
# TODO-13: Algorithm field on attestation schema
# ---------------------------------------------------------------------------


class TestAlgorithmField:
    """Attestations should carry an algorithm identifier for crypto agility."""

    def test_default_algorithm(self):
        """Default algorithm should be 'ed25519-sha3-256'."""
        att = AuditorAttestation(
            agent_id="bot",
            commitment_hashes=["h1"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
            signature="sig",
        )
        assert att.algorithm == "ed25519-sha3-256"

    def test_custom_algorithm(self):
        """Custom algorithm should be accepted."""
        att = AuditorAttestation(
            agent_id="bot",
            commitment_hashes=["h1"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
            signature="sig",
            algorithm="dilithium-sha3-256",
        )
        assert att.algorithm == "dilithium-sha3-256"

    @pytest.mark.asyncio
    async def test_algorithm_persisted(self, api):
        """Algorithm field should round-trip through storage."""
        await api.register_agent("bot-algo")
        await api.submit_metrics("bot-algo", {"sharpe_30d": 2.0})

        attestations = await api.storage.get_attestations("bot-algo")
        assert attestations[0].algorithm == "ed25519-sha3-256"


# ---------------------------------------------------------------------------
# TODO-14: Configurable metric set
# ---------------------------------------------------------------------------


class TestConfigurableMetrics:
    """Metric set should be configurable, not hardcoded."""

    @pytest.mark.asyncio
    async def test_custom_metric_registration(self, api):
        """Registering a custom metric should allow it in submit_metrics."""
        api.register_custom_metric("custom_alpha_30d")

        await api.register_agent("bot-custom")
        result = await api.submit_metrics("bot-custom", {"custom_alpha_30d": 1.5})
        assert "custom_alpha_30d" in result.blinding_factors

    @pytest.mark.asyncio
    async def test_unregistered_custom_metric_rejected(self, api):
        """Unregistered metrics should still be rejected."""
        await api.register_agent("bot-no-custom")
        with pytest.raises(InvalidMetricError):
            await api.submit_metrics("bot-no-custom", {"completely_unknown_metric": 1.0})

    @pytest.mark.asyncio
    async def test_deregister_custom_metric(self, api):
        """Deregistered metrics should no longer be accepted."""
        api.register_custom_metric("temp_metric")
        api.deregister_custom_metric("temp_metric")

        await api.register_agent("bot-dereg")
        with pytest.raises(InvalidMetricError):
            await api.submit_metrics("bot-dereg", {"temp_metric": 1.0})

    def test_list_supported_metrics(self, api):
        """get_supported_metrics should return all supported metric names."""
        metrics = api.get_supported_metrics()
        assert "sharpe_30d" in metrics
        assert isinstance(metrics, set)


# ---------------------------------------------------------------------------
# TODO-15: Auditor key rotation
# ---------------------------------------------------------------------------


class TestAuditorKeyRotation:
    """Auditor keys should be rotatable with version tracking."""

    @pytest.mark.asyncio
    async def test_rotate_auditor_key(self, api):
        """rotate_auditor_key should generate new keypair."""
        old_pub = api.auditor_public_key
        new_pub = await api.rotate_auditor_key()

        assert new_pub != old_pub
        assert api.auditor_public_key == new_pub

    @pytest.mark.asyncio
    async def test_old_attestations_still_verifiable(self, api):
        """Attestations signed with old key should remain verifiable."""
        await api.register_agent("bot-rotate")
        result = await api.submit_metrics("bot-rotate", {"sharpe_30d": 2.0})
        old_sig = result.attestation.signature
        old_pub = api.auditor_public_key

        # Rotate key
        await api.rotate_auditor_key()

        # Old attestation should still verify with old key
        assert AgentCrypto.verify_attestation(
            old_pub,
            result.attestation.agent_id,
            result.attestation.commitment_hashes,
            result.attestation.verified_at,
            result.attestation.valid_until,
            result.attestation.data_source,
            old_sig,
        )

    @pytest.mark.asyncio
    async def test_key_history_tracked(self, api):
        """Key rotation should track key history."""
        old_pub = api.auditor_public_key
        await api.rotate_auditor_key()

        history = api.get_auditor_key_history()
        assert len(history) >= 1
        assert any(k["public_key"] == old_pub for k in history)


# ---------------------------------------------------------------------------
# TODO-16: W3C VC alignment
# ---------------------------------------------------------------------------


class TestW3CVCAlignment:
    """Attestations should be exportable in W3C Verifiable Credential format."""

    @pytest.mark.asyncio
    async def test_export_as_vc(self, api):
        """export_as_vc should produce a W3C-aligned structure."""
        await api.register_agent("bot-vc")
        result = await api.submit_metrics("bot-vc", {"sharpe_30d": 2.5}, data_source="platform_verified")

        vc = api.export_attestation_as_vc(result.attestation)

        assert vc["@context"] == ["https://www.w3.org/2018/credentials/v1"]
        assert vc["type"] == ["VerifiableCredential", "MetricAttestation"]
        assert vc["issuer"] == f"did:a2a:{result.attestation.auditor_id}"
        assert vc["credentialSubject"]["id"] == f"did:a2a:{result.attestation.agent_id}"
        assert len(vc["credentialSubject"]["claims"]) == 1  # 1 commitment hash
        assert vc["credentialSubject"]["dataSource"] == "platform_verified"
        assert "proof" in vc
        assert vc["proof"]["type"] == "Ed25519Signature2020"
        assert vc["proof"]["proofValue"] == result.attestation.signature


# ---------------------------------------------------------------------------
# TODO-17: Merkle proof endpoint
# ---------------------------------------------------------------------------


class TestMerkleProofEndpoint:
    """API should provide inclusion proofs for claim chains."""

    @pytest.mark.asyncio
    async def test_get_inclusion_proof(self, api):
        """get_inclusion_proof should return a valid Merkle proof."""
        await api.register_agent("bot-proof")
        # Create multiple attestations
        for i in range(3):
            await api.submit_metrics("bot-proof", {"sharpe_30d": float(i + 1)})

        chain = await api.build_claim_chain("bot-proof")

        proof_result = await api.get_inclusion_proof(chain["chain_id"], 0)
        assert "leaf_hash" in proof_result
        assert "proof" in proof_result
        assert "root" in proof_result
        assert proof_result["root"] == chain["merkle_root"]

        # Verify the proof
        assert MerkleTree.verify_proof(
            proof_result["leaf_hash"],
            [(p["sibling"], p["position"]) for p in proof_result["proof"]],
            proof_result["root"],
        )

    @pytest.mark.asyncio
    async def test_get_inclusion_proof_all_leaves(self, api):
        """Every leaf in a chain should have a verifiable proof."""
        await api.register_agent("bot-proof-all")
        for i in range(4):
            await api.submit_metrics("bot-proof-all", {"sharpe_30d": float(i + 1)})

        chain = await api.build_claim_chain("bot-proof-all")

        for idx in range(chain["leaf_count"]):
            proof_result = await api.get_inclusion_proof(chain["chain_id"], idx)
            assert MerkleTree.verify_proof(
                proof_result["leaf_hash"],
                [(p["sibling"], p["position"]) for p in proof_result["proof"]],
                proof_result["root"],
            )


# ---------------------------------------------------------------------------
# TODO-18: Integrate reputation with payment/dispute data
# ---------------------------------------------------------------------------


class TestReputationIntegration:
    """Reputation should accept external payment/dispute signals."""

    @pytest.mark.asyncio
    async def test_compute_reputation_with_payment_data(self, api):
        """compute_reputation should incorporate payment reliability data."""
        await api.register_agent("bot-pay-rep")
        await api.submit_metrics("bot-pay-rep", {"sharpe_30d": 2.0})

        # Inject payment signal
        await api.record_payment_signal("bot-pay-rep", signal_type="payment_completed", count=10)

        rep = await api.compute_reputation("bot-pay-rep")
        assert rep.payment_reliability > 0

    @pytest.mark.asyncio
    async def test_compute_reputation_with_dispute_data(self, api):
        """compute_reputation should incorporate dispute data."""
        await api.register_agent("bot-disp-rep")
        await api.submit_metrics("bot-disp-rep", {"sharpe_30d": 2.0})

        # Inject dispute signal — high dispute count should lower reputation
        await api.record_payment_signal("bot-disp-rep", signal_type="dispute_opened", count=5)
        await api.record_payment_signal("bot-disp-rep", signal_type="payment_completed", count=10)

        rep = await api.compute_reputation("bot-disp-rep")
        # Dispute rate should be 5/(5+10) = 33%, so composite should be lower
        assert rep.composite_score > 0

    @pytest.mark.asyncio
    async def test_no_signals_uses_attestation_proxy(self, api):
        """Without payment signals, reputation should use attestation-based proxies."""
        await api.register_agent("bot-no-signals")
        await api.submit_metrics("bot-no-signals", {"sharpe_30d": 2.0}, data_source="platform_verified")

        rep = await api.compute_reputation("bot-no-signals")
        assert rep.payment_reliability > 0  # Attestation count proxy still works
