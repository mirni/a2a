"""TDD tests for the crypto module: Ed25519 keys and HMAC-based commitments."""

from __future__ import annotations

import pytest

from products.identity.src.crypto import AgentCrypto


class TestEd25519KeyPair:
    """Ed25519 key generation tests."""

    def test_generate_keypair_returns_valid_keys(self):
        """generate_keypair should return (private_hex, public_hex) with correct lengths."""
        priv, pub = AgentCrypto.generate_keypair()
        # Ed25519 private key is 32 bytes = 64 hex chars
        assert len(priv) == 64
        # Ed25519 public key is 32 bytes = 64 hex chars
        assert len(pub) == 64
        # They should be valid hex
        bytes.fromhex(priv)
        bytes.fromhex(pub)

    def test_generate_keypair_returns_unique_keys(self):
        """Each call should produce a different keypair."""
        priv1, pub1 = AgentCrypto.generate_keypair()
        priv2, pub2 = AgentCrypto.generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestSignAndVerify:
    """Ed25519 sign/verify roundtrip tests."""

    def test_sign_and_verify_roundtrip(self):
        """A message signed with a private key should verify with the matching public key."""
        priv, pub = AgentCrypto.generate_keypair()
        message = b"hello agent commerce"
        sig = AgentCrypto.sign(priv, message)
        assert isinstance(sig, str)
        # Ed25519 signature is 64 bytes = 128 hex chars
        assert len(sig) == 128
        assert AgentCrypto.verify(pub, message, sig) is True

    def test_verify_fails_with_wrong_key(self):
        """Verification with a different public key should fail."""
        priv1, _pub1 = AgentCrypto.generate_keypair()
        _priv2, pub2 = AgentCrypto.generate_keypair()
        message = b"signed by agent 1"
        sig = AgentCrypto.sign(priv1, message)
        assert AgentCrypto.verify(pub2, message, sig) is False

    def test_verify_fails_with_tampered_message(self):
        """Verification with a modified message should fail."""
        priv, pub = AgentCrypto.generate_keypair()
        message = b"original message"
        sig = AgentCrypto.sign(priv, message)
        assert AgentCrypto.verify(pub, b"tampered message", sig) is False

    def test_verify_fails_with_tampered_signature(self):
        """Verification with a corrupted signature should fail."""
        priv, pub = AgentCrypto.generate_keypair()
        message = b"test message"
        sig = AgentCrypto.sign(priv, message)
        # Flip a byte in the signature
        bad_sig = "00" + sig[2:]
        if bad_sig == sig:
            bad_sig = "ff" + sig[2:]
        assert AgentCrypto.verify(pub, message, bad_sig) is False


class TestCommitments:
    """HMAC-based hiding commitment tests."""

    def test_create_commitment_produces_hex_hash(self):
        """create_commitment should return a valid SHA3-256 hex hash and blinding factor."""
        commit_hash, blinding = AgentCrypto.create_commitment(2.35, "sharpe_30d")
        # SHA3-256 is 32 bytes = 64 hex chars
        assert len(commit_hash) == 64
        # Blinding factor is 32 bytes = 64 hex chars
        assert len(blinding) == 64
        bytes.fromhex(commit_hash)
        bytes.fromhex(blinding)

    def test_create_commitment_is_deterministic_with_same_blinding(self):
        """Given the same value, metric_name, and blinding factor, the commitment should match."""
        import hashlib

        value = 2.35
        metric_name = "sharpe_30d"
        scale = 10000

        commit_hash, blinding = AgentCrypto.create_commitment(value, metric_name, scale)

        # Recompute manually
        value_bytes = str(int(value * scale)).encode()
        blinding_bytes = bytes.fromhex(blinding)
        expected = hashlib.sha3_256(
            value_bytes + blinding_bytes + metric_name.encode()
        ).hexdigest()
        assert commit_hash == expected

    def test_verify_commitment_roundtrip(self):
        """verify_commitment should return True for the original value."""
        value = 5.67
        metric_name = "pnl_30d"
        commit_hash, blinding = AgentCrypto.create_commitment(value, metric_name)
        assert AgentCrypto.verify_commitment(
            value, metric_name, blinding, commit_hash
        ) is True

    def test_verify_commitment_fails_with_wrong_value(self):
        """verify_commitment should return False for a different value."""
        commit_hash, blinding = AgentCrypto.create_commitment(2.35, "sharpe_30d")
        assert AgentCrypto.verify_commitment(
            9.99, "sharpe_30d", blinding, commit_hash
        ) is False

    def test_commitment_hides_value(self):
        """Same metric name with different values should produce different hashes."""
        hash1, _ = AgentCrypto.create_commitment(2.35, "sharpe_30d")
        hash2, _ = AgentCrypto.create_commitment(3.50, "sharpe_30d")
        assert hash1 != hash2

    def test_commitment_different_metrics_different_hashes(self):
        """Same value with different metric names should produce different hashes
        (even if blinding happened to be the same, the metric_name salt differs)."""
        hash1, _ = AgentCrypto.create_commitment(100.0, "aum")
        hash2, _ = AgentCrypto.create_commitment(100.0, "pnl_30d")
        assert hash1 != hash2


class TestAttestationSigning:
    """Attestation sign/verify tests."""

    def test_sign_and_verify_attestation_roundtrip(self):
        """A signed attestation should verify with the auditor's public key."""
        priv, pub = AgentCrypto.generate_keypair()
        sig = AgentCrypto.sign_attestation(
            priv,
            agent_id="agent-1",
            commitment_hashes=["aabb", "ccdd"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
        )
        assert AgentCrypto.verify_attestation(
            pub,
            agent_id="agent-1",
            commitment_hashes=["aabb", "ccdd"],
            verified_at=1000.0,
            valid_until=2000.0,
            data_source="self_reported",
            signature_hex=sig,
        ) is True

    def test_verify_attestation_fails_with_tampered_agent_id(self):
        """Changing the agent_id should invalidate the attestation."""
        priv, pub = AgentCrypto.generate_keypair()
        sig = AgentCrypto.sign_attestation(
            priv, "agent-1", ["hash1"], 1000.0, 2000.0, "self_reported"
        )
        assert AgentCrypto.verify_attestation(
            pub, "agent-2", ["hash1"], 1000.0, 2000.0, "self_reported", sig
        ) is False
