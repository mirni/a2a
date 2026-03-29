"""TDD tests for P0 critical fixes (TODOs 1-3).

TODO-1: Blinding factors stored and retrievable; reveal_commitment workflow.
TODO-2: Auditor keypair persistence from env vars.
TODO-3: Agent private key returned on auto-registration.
"""

from __future__ import annotations

import os

import pytest

from products.identity.src.api import IdentityAPI
from products.identity.src.crypto import AgentCrypto
from products.identity.src.storage import IdentityStorage

# ---------------------------------------------------------------------------
# TODO-1: Store blinding factors + reveal_commitment
# ---------------------------------------------------------------------------


class TestBlindingFactorStorage:
    """Blinding factors must be stored so commitments can be opened later."""

    @pytest.mark.asyncio
    async def test_submit_metrics_returns_blinding_factors(self, api):
        """submit_metrics should return blinding factors alongside the attestation."""
        await api.register_agent("bot-blind")
        result = await api.submit_metrics("bot-blind", {"sharpe_30d": 2.5})
        # Result should now be a dict/object with attestation AND blinding_factors
        assert hasattr(result, "blinding_factors") or isinstance(result, dict)
        # For backward compat, we'll use a richer return type
        # The attestation is still accessible
        assert result.attestation.agent_id == "bot-blind"
        assert "sharpe_30d" in result.blinding_factors
        # Blinding factor is 64-char hex (32 bytes)
        assert len(result.blinding_factors["sharpe_30d"]) == 64
        bytes.fromhex(result.blinding_factors["sharpe_30d"])

    @pytest.mark.asyncio
    async def test_blinding_factors_stored_in_db(self, api):
        """Blinding factors should be persisted in commitment_secrets table."""
        await api.register_agent("bot-blind-db")
        result = await api.submit_metrics("bot-blind-db", {"sharpe_30d": 1.8, "aum": 50000.0})
        # Should be retrievable from storage
        secrets = await api.storage.get_commitment_secrets("bot-blind-db", "sharpe_30d")
        assert len(secrets) >= 1
        assert secrets[0]["blinding_factor"] == result.blinding_factors["sharpe_30d"]

    @pytest.mark.asyncio
    async def test_reveal_commitment_success(self, api):
        """reveal_commitment should verify and return the revealed value."""
        await api.register_agent("bot-reveal")
        result = await api.submit_metrics("bot-reveal", {"sharpe_30d": 2.35})
        blinding = result.blinding_factors["sharpe_30d"]
        result.attestation.commitment_hashes[0]

        revealed = await api.reveal_commitment("bot-reveal", "sharpe_30d", 2.35, blinding)
        assert revealed["verified"] is True
        assert revealed["metric_name"] == "sharpe_30d"
        assert revealed["value"] == 2.35

    @pytest.mark.asyncio
    async def test_reveal_commitment_wrong_value(self, api):
        """reveal_commitment with wrong value should fail verification."""
        await api.register_agent("bot-reveal-bad")
        result = await api.submit_metrics("bot-reveal-bad", {"sharpe_30d": 2.35})
        blinding = result.blinding_factors["sharpe_30d"]

        revealed = await api.reveal_commitment("bot-reveal-bad", "sharpe_30d", 9.99, blinding)
        assert revealed["verified"] is False

    @pytest.mark.asyncio
    async def test_reveal_commitment_wrong_blinding(self, api):
        """reveal_commitment with wrong blinding factor should fail."""
        await api.register_agent("bot-reveal-bad2")
        await api.submit_metrics("bot-reveal-bad2", {"sharpe_30d": 2.35})

        revealed = await api.reveal_commitment("bot-reveal-bad2", "sharpe_30d", 2.35, "ff" * 32)
        assert revealed["verified"] is False


# ---------------------------------------------------------------------------
# TODO-2: Persist auditor keypair
# ---------------------------------------------------------------------------


class TestAuditorKeyPersistence:
    """Auditor keypair should be loadable from env vars."""

    @pytest.mark.asyncio
    async def test_auditor_key_from_env(self, tmp_path):
        """IdentityAPI should load auditor keys from environment variables."""
        priv, pub = AgentCrypto.generate_keypair()
        os.environ["AUDITOR_PRIVATE_KEY"] = priv
        os.environ["AUDITOR_PUBLIC_KEY"] = pub
        try:
            s = IdentityStorage(dsn=f"sqlite:///{tmp_path}/env_test.db")
            await s.connect()
            api = IdentityAPI.from_env(storage=s)
            assert api.auditor_private_key == priv
            assert api.auditor_public_key == pub
            await s.close()
        finally:
            del os.environ["AUDITOR_PRIVATE_KEY"]
            del os.environ["AUDITOR_PUBLIC_KEY"]

    @pytest.mark.asyncio
    async def test_auditor_key_falls_back_to_generation(self, tmp_path):
        """Without env vars, IdentityAPI should auto-generate (existing behavior)."""
        # Ensure env vars are not set
        os.environ.pop("AUDITOR_PRIVATE_KEY", None)
        os.environ.pop("AUDITOR_PUBLIC_KEY", None)

        s = IdentityStorage(dsn=f"sqlite:///{tmp_path}/fallback_test.db")
        await s.connect()
        api = IdentityAPI.from_env(storage=s)
        assert len(api.auditor_private_key) == 64
        assert len(api.auditor_public_key) == 64
        await s.close()

    @pytest.mark.asyncio
    async def test_attestations_verifiable_with_persisted_key(self, tmp_path):
        """Attestation signed with persisted key should verify with same key."""
        priv, pub = AgentCrypto.generate_keypair()

        s = IdentityStorage(dsn=f"sqlite:///{tmp_path}/verify_test.db")
        await s.connect()
        api = IdentityAPI(storage=s, auditor_private_key=priv, auditor_public_key=pub)
        await api.register_agent("bot-persist")
        result = await api.submit_metrics("bot-persist", {"sharpe_30d": 2.0})

        # Verify with the known public key
        assert AgentCrypto.verify_attestation(
            pub,
            result.attestation.agent_id,
            result.attestation.commitment_hashes,
            result.attestation.verified_at,
            result.attestation.valid_until,
            result.attestation.data_source,
            result.attestation.signature,
        )
        await s.close()


# ---------------------------------------------------------------------------
# TODO-3: Return agent private key on auto-registration
# ---------------------------------------------------------------------------


class TestAgentPrivateKeyReturn:
    """Auto-registration should return the private key to the caller."""

    @pytest.mark.asyncio
    async def test_auto_register_returns_private_key(self, api):
        """register_agent without public_key should return identity + private_key."""
        result = await api.register_agent("bot-auto-priv")
        # Result should contain private_key
        assert result.private_key is not None
        assert len(result.private_key) == 64
        bytes.fromhex(result.private_key)

    @pytest.mark.asyncio
    async def test_explicit_register_no_private_key(self, api):
        """register_agent with explicit public_key should NOT return a private key."""
        _priv, pub = AgentCrypto.generate_keypair()
        result = await api.register_agent("bot-explicit-priv", public_key=pub)
        assert result.private_key is None

    @pytest.mark.asyncio
    async def test_returned_private_key_can_sign_and_verify(self, api):
        """The returned private key should produce signatures verifiable with the stored public key."""
        result = await api.register_agent("bot-sign-test")

        message = b"test message for signing"
        sig = AgentCrypto.sign(result.private_key, message)
        assert await api.verify_agent("bot-sign-test", message, sig) is True

    @pytest.mark.asyncio
    async def test_private_key_not_stored_in_db(self, api):
        """Private key should NOT be stored in the database."""
        result = await api.register_agent("bot-no-store")

        # Retrieve from DB — should only have public_key
        identity = await api.storage.get_identity("bot-no-store")
        assert identity is not None
        assert identity.public_key == result.identity.public_key
        # The identity model should not contain private_key
        assert not hasattr(identity, "private_key") or identity.private_key is None
