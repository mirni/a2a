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
        expected = hashlib.sha3_256(value_bytes + blinding_bytes + metric_name.encode()).hexdigest()
        assert commit_hash == expected

    def test_verify_commitment_roundtrip(self):
        """verify_commitment should return True for the original value."""
        value = 5.67
        metric_name = "pnl_30d"
        commit_hash, blinding = AgentCrypto.create_commitment(value, metric_name)
        assert AgentCrypto.verify_commitment(value, metric_name, blinding, commit_hash) is True

    def test_verify_commitment_fails_with_wrong_value(self):
        """verify_commitment should return False for a different value."""
        commit_hash, blinding = AgentCrypto.create_commitment(2.35, "sharpe_30d")
        assert AgentCrypto.verify_commitment(9.99, "sharpe_30d", blinding, commit_hash) is False

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
        assert (
            AgentCrypto.verify_attestation(
                pub,
                agent_id="agent-1",
                commitment_hashes=["aabb", "ccdd"],
                verified_at=1000.0,
                valid_until=2000.0,
                data_source="self_reported",
                signature_hex=sig,
            )
            is True
        )

    def test_verify_attestation_fails_with_tampered_agent_id(self):
        """Changing the agent_id should invalidate the attestation."""
        priv, pub = AgentCrypto.generate_keypair()
        sig = AgentCrypto.sign_attestation(priv, "agent-1", ["hash1"], 1000.0, 2000.0, "self_reported")
        assert AgentCrypto.verify_attestation(pub, "agent-2", ["hash1"], 1000.0, 2000.0, "self_reported", sig) is False


class TestMerkleTreeComputeRoot:
    """Tests for MerkleTree.compute_root."""

    def test_empty_tree_returns_hash_of_empty(self):
        """An empty leaf list should return the SHA3-256 hash of the empty string."""
        import hashlib

        from products.identity.src.crypto import MerkleTree

        expected = hashlib.sha3_256(b"").hexdigest()
        assert MerkleTree.compute_root([]) == expected

    def test_single_leaf_returns_itself(self):
        """A single leaf should be its own Merkle root."""
        from products.identity.src.crypto import MerkleTree

        leaf = "aa" * 32
        assert MerkleTree.compute_root([leaf]) == leaf

    def test_two_leaves(self):
        """Two leaves should produce root = H(leaf0 || leaf1)."""
        import hashlib

        from products.identity.src.crypto import MerkleTree

        leaf0 = "aa" * 32
        leaf1 = "bb" * 32
        expected = hashlib.sha3_256(bytes.fromhex(leaf0) + bytes.fromhex(leaf1)).hexdigest()
        assert MerkleTree.compute_root([leaf0, leaf1]) == expected

    def test_three_leaves_duplicates_last(self):
        """Odd number of leaves should duplicate the last leaf to make it even."""
        import hashlib

        from products.identity.src.crypto import MerkleTree

        leaf0 = "aa" * 32
        leaf1 = "bb" * 32
        leaf2 = "cc" * 32
        # Level 1: H(leaf0||leaf1), H(leaf2||leaf2)
        h01 = hashlib.sha3_256(bytes.fromhex(leaf0) + bytes.fromhex(leaf1)).hexdigest()
        h22 = hashlib.sha3_256(bytes.fromhex(leaf2) + bytes.fromhex(leaf2)).hexdigest()
        # Root: H(h01||h22)
        expected = hashlib.sha3_256(bytes.fromhex(h01) + bytes.fromhex(h22)).hexdigest()
        assert MerkleTree.compute_root([leaf0, leaf1, leaf2]) == expected

    def test_four_leaves(self):
        """Four leaves: balanced binary tree."""
        import hashlib

        from products.identity.src.crypto import MerkleTree

        leaves = [f"{chr(ord('a') + i):02s}" * 32 for i in range(4)]
        h01 = hashlib.sha3_256(bytes.fromhex(leaves[0]) + bytes.fromhex(leaves[1])).hexdigest()
        h23 = hashlib.sha3_256(bytes.fromhex(leaves[2]) + bytes.fromhex(leaves[3])).hexdigest()
        expected = hashlib.sha3_256(bytes.fromhex(h01) + bytes.fromhex(h23)).hexdigest()
        assert MerkleTree.compute_root(leaves) == expected

    def test_root_is_deterministic(self):
        """Same leaves in same order should always produce the same root."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["ab" * 32, "cd" * 32, "ef" * 32]
        root1 = MerkleTree.compute_root(leaves)
        root2 = MerkleTree.compute_root(leaves)
        assert root1 == root2

    def test_root_changes_with_different_order(self):
        """Different leaf order should produce a different root (Merkle trees are ordered)."""
        from products.identity.src.crypto import MerkleTree

        leaves_a = ["aa" * 32, "bb" * 32]
        leaves_b = ["bb" * 32, "aa" * 32]
        assert MerkleTree.compute_root(leaves_a) != MerkleTree.compute_root(leaves_b)

    def test_root_is_valid_hex(self):
        """Root should be a valid 64-char hex string (SHA3-256)."""
        from products.identity.src.crypto import MerkleTree

        root = MerkleTree.compute_root(["aa" * 32, "bb" * 32, "cc" * 32])
        assert len(root) == 64
        bytes.fromhex(root)  # Should not raise


class TestMerkleTreeComputeProof:
    """Tests for MerkleTree.compute_proof."""

    def test_single_leaf_proof_is_empty(self):
        """A single-leaf tree has no siblings, so proof is empty."""
        from products.identity.src.crypto import MerkleTree

        proof = MerkleTree.compute_proof(["aa" * 32], 0)
        assert proof == []

    def test_two_leaves_proof_for_left(self):
        """Proof for left leaf (index 0) should include right sibling."""
        from products.identity.src.crypto import MerkleTree

        leaf0 = "aa" * 32
        leaf1 = "bb" * 32
        proof = MerkleTree.compute_proof([leaf0, leaf1], 0)
        assert len(proof) == 1
        assert proof[0] == (leaf1, "right")

    def test_two_leaves_proof_for_right(self):
        """Proof for right leaf (index 1) should include left sibling."""
        from products.identity.src.crypto import MerkleTree

        leaf0 = "aa" * 32
        leaf1 = "bb" * 32
        proof = MerkleTree.compute_proof([leaf0, leaf1], 1)
        assert len(proof) == 1
        assert proof[0] == (leaf0, "left")

    def test_four_leaves_proof_depth(self):
        """Proof for 4 leaves should have depth 2 (log2(4) = 2)."""
        from products.identity.src.crypto import MerkleTree

        leaves = [f"{chr(ord('a') + i):02s}" * 32 for i in range(4)]
        proof = MerkleTree.compute_proof(leaves, 2)
        assert len(proof) == 2

    def test_proof_index_out_of_range_raises(self):
        """Out-of-range leaf index should raise IndexError."""
        from products.identity.src.crypto import MerkleTree

        with pytest.raises(IndexError):
            MerkleTree.compute_proof(["aa" * 32], 1)

    def test_proof_negative_index_raises(self):
        """Negative leaf index should raise IndexError."""
        from products.identity.src.crypto import MerkleTree

        with pytest.raises(IndexError):
            MerkleTree.compute_proof(["aa" * 32, "bb" * 32], -1)

    def test_proof_empty_tree_raises(self):
        """Empty tree should raise IndexError for any index."""
        from products.identity.src.crypto import MerkleTree

        with pytest.raises(IndexError):
            MerkleTree.compute_proof([], 0)


class TestMerkleTreeVerifyProof:
    """Tests for MerkleTree.verify_proof."""

    def test_verify_single_leaf(self):
        """Single leaf: proof is empty, root equals the leaf."""
        from products.identity.src.crypto import MerkleTree

        leaf = "aa" * 32
        root = MerkleTree.compute_root([leaf])
        proof = MerkleTree.compute_proof([leaf], 0)
        assert MerkleTree.verify_proof(leaf, proof, root) is True

    def test_verify_two_leaves_both_indices(self):
        """Proof for either leaf in a 2-leaf tree should verify."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["aa" * 32, "bb" * 32]
        root = MerkleTree.compute_root(leaves)
        for i in range(2):
            proof = MerkleTree.compute_proof(leaves, i)
            assert MerkleTree.verify_proof(leaves[i], proof, root) is True

    def test_verify_four_leaves_all_indices(self):
        """Proof for every leaf in a 4-leaf tree should verify."""
        from products.identity.src.crypto import MerkleTree

        leaves = [f"{chr(ord('a') + i):02s}" * 32 for i in range(4)]
        root = MerkleTree.compute_root(leaves)
        for i in range(4):
            proof = MerkleTree.compute_proof(leaves, i)
            assert MerkleTree.verify_proof(leaves[i], proof, root) is True

    def test_verify_odd_leaf_count(self):
        """Proof should also work for trees with odd number of leaves."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["aa" * 32, "bb" * 32, "cc" * 32]
        root = MerkleTree.compute_root(leaves)
        for i in range(3):
            proof = MerkleTree.compute_proof(leaves, i)
            assert MerkleTree.verify_proof(leaves[i], proof, root) is True

    def test_verify_fails_with_wrong_leaf(self):
        """Verification should fail if the leaf hash does not match."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["aa" * 32, "bb" * 32]
        root = MerkleTree.compute_root(leaves)
        proof = MerkleTree.compute_proof(leaves, 0)
        assert MerkleTree.verify_proof("ff" * 32, proof, root) is False

    def test_verify_fails_with_wrong_root(self):
        """Verification should fail against a different root."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["aa" * 32, "bb" * 32]
        MerkleTree.compute_root(leaves)
        proof = MerkleTree.compute_proof(leaves, 0)
        assert MerkleTree.verify_proof(leaves[0], proof, "00" * 32) is False

    def test_verify_fails_with_tampered_proof(self):
        """Verification should fail if a proof element is tampered."""
        from products.identity.src.crypto import MerkleTree

        leaves = ["aa" * 32, "bb" * 32, "cc" * 32, "dd" * 32]
        root = MerkleTree.compute_root(leaves)
        proof = MerkleTree.compute_proof(leaves, 0)
        # Tamper with the first proof element
        tampered = [("ff" * 32, proof[0][1])] + proof[1:]
        assert MerkleTree.verify_proof(leaves[0], tampered, root) is False

    def test_verify_larger_tree(self):
        """Roundtrip verify for a 7-leaf tree (odd, multiple levels)."""
        import hashlib

        from products.identity.src.crypto import MerkleTree

        leaves = [hashlib.sha3_256(f"leaf-{i}".encode()).hexdigest() for i in range(7)]
        root = MerkleTree.compute_root(leaves)
        for i in range(7):
            proof = MerkleTree.compute_proof(leaves, i)
            assert MerkleTree.verify_proof(leaves[i], proof, root) is True
