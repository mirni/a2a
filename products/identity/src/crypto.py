"""Cryptographic operations for the Agent Identity system.

Ed25519 key generation, signing, and verification via the `cryptography` package.
HMAC-based hiding commitments for numeric metric values using SHA3-256.
"""

from __future__ import annotations

import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


class AgentCrypto:
    """Handles Ed25519 key generation and metric commitments."""

    @staticmethod
    def generate_keypair() -> tuple[str, str]:
        """Generate Ed25519 keypair.

        Returns:
            (private_key_hex, public_key_hex) — raw key bytes encoded as hex.
        """
        private_key = Ed25519PrivateKey.generate()
        private_bytes = private_key.private_bytes(
            Encoding.Raw, PrivateFormat.Raw, NoEncryption()
        )
        public_bytes = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        return private_bytes.hex(), public_bytes.hex()

    @staticmethod
    def sign(private_key_hex: str, message: bytes) -> str:
        """Sign a message with Ed25519.

        Args:
            private_key_hex: Raw private key bytes as hex string.
            message: Bytes to sign.

        Returns:
            Signature as hex string.
        """
        private_key = Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(private_key_hex)
        )
        signature = private_key.sign(message)
        return signature.hex()

    @staticmethod
    def verify(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
        """Verify an Ed25519 signature.

        Args:
            public_key_hex: Raw public key bytes as hex string.
            message: Original signed bytes.
            signature_hex: Signature as hex string.

        Returns:
            True if the signature is valid, False otherwise.
        """
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(public_key_hex)
            )
            public_key.verify(bytes.fromhex(signature_hex), message)
            return True
        except Exception:
            return False

    @staticmethod
    def create_commitment(
        value: float, metric_name: str, scale: int = 10000
    ) -> tuple[str, str]:
        """Create an HMAC-based hiding commitment to a numeric value.

        commitment = SHA3-256(value_scaled_bytes || blinding_factor || metric_name)

        Args:
            value: The numeric metric value (e.g. 2.35 for Sharpe ratio).
            metric_name: Metric identifier (e.g. "sharpe_30d").
            scale: Integer scaling factor (default 10000 for 4 decimal places).

        Returns:
            (commitment_hash_hex, blinding_factor_hex)
        """
        blinding = os.urandom(32)
        value_bytes = str(int(value * scale)).encode()
        commitment = hashlib.sha3_256(
            value_bytes + blinding + metric_name.encode()
        ).hexdigest()
        return commitment, blinding.hex()

    @staticmethod
    def verify_commitment(
        value: float,
        metric_name: str,
        blinding_factor_hex: str,
        commitment_hash: str,
        scale: int = 10000,
    ) -> bool:
        """Verify that a commitment matches the claimed value.

        Args:
            value: The claimed metric value.
            metric_name: Metric identifier.
            blinding_factor_hex: The blinding factor used during commitment.
            commitment_hash: The original commitment hash to verify against.
            scale: Integer scaling factor.

        Returns:
            True if the commitment matches.
        """
        blinding = bytes.fromhex(blinding_factor_hex)
        value_bytes = str(int(value * scale)).encode()
        recomputed = hashlib.sha3_256(
            value_bytes + blinding + metric_name.encode()
        ).hexdigest()
        return recomputed == commitment_hash

    @staticmethod
    def sign_attestation(
        private_key_hex: str,
        agent_id: str,
        commitment_hashes: list[str],
        verified_at: float,
        valid_until: float,
        data_source: str,
    ) -> str:
        """Sign an attestation payload with the auditor's private key.

        The canonical message is JSON with sorted keys:
        {"agent_id": ..., "commitment_hashes": [...], "data_source": ...,
         "valid_until": ..., "verified_at": ...}

        Returns:
            Signature hex string.
        """
        payload = {
            "agent_id": agent_id,
            "commitment_hashes": commitment_hashes,
            "data_source": data_source,
            "valid_until": valid_until,
            "verified_at": verified_at,
        }
        message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return AgentCrypto.sign(private_key_hex, message)

    @staticmethod
    def verify_attestation(
        public_key_hex: str,
        agent_id: str,
        commitment_hashes: list[str],
        verified_at: float,
        valid_until: float,
        data_source: str,
        signature_hex: str,
    ) -> bool:
        """Verify an attestation signature.

        Returns:
            True if the signature is valid.
        """
        payload = {
            "agent_id": agent_id,
            "commitment_hashes": commitment_hashes,
            "data_source": data_source,
            "valid_until": valid_until,
            "verified_at": verified_at,
        }
        message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return AgentCrypto.verify(public_key_hex, message, signature_hex)


class MerkleTree:
    """Simple SHA3-256 Merkle tree for attestation chains.

    Used to build verifiable claim chains: an agent can prove
    "I had Sharpe > 2.0 for the past 6 months" by chaining
    attestation hashes into a Merkle tree and providing inclusion proofs.
    """

    @staticmethod
    def _hash_pair(left: str, right: str) -> str:
        """Hash two hex strings together: SHA3-256(left_bytes || right_bytes)."""
        return hashlib.sha3_256(
            bytes.fromhex(left) + bytes.fromhex(right)
        ).hexdigest()

    @staticmethod
    def compute_root(leaf_hashes: list[str]) -> str:
        """Compute Merkle root from a list of hex hash strings.

        - Empty list: returns SHA3-256 of empty string.
        - Single leaf: returns the leaf itself.
        - Otherwise: pair leaves (duplicate last if odd), hash pairs, recurse.

        Args:
            leaf_hashes: List of hex-encoded hash strings (the leaves).

        Returns:
            Hex-encoded SHA3-256 Merkle root.
        """
        if not leaf_hashes:
            return hashlib.sha3_256(b"").hexdigest()
        if len(leaf_hashes) == 1:
            return leaf_hashes[0]

        # Build one level up
        level = list(leaf_hashes)
        while len(level) > 1:
            next_level: list[str] = []
            # If odd, duplicate the last element
            if len(level) % 2 == 1:
                level.append(level[-1])
            for i in range(0, len(level), 2):
                next_level.append(MerkleTree._hash_pair(level[i], level[i + 1]))
            level = next_level

        return level[0]

    @staticmethod
    def compute_proof(
        leaf_hashes: list[str], leaf_index: int
    ) -> list[tuple[str, str]]:
        """Compute a Merkle proof (authentication path) for a specific leaf.

        Args:
            leaf_hashes: List of hex-encoded hash strings (the leaves).
            leaf_index: Index of the leaf to prove.

        Returns:
            List of (sibling_hash, position) tuples where position is
            'left' or 'right', indicating where the sibling sits relative
            to the current node.

        Raises:
            IndexError: If leaf_index is out of range or list is empty.
        """
        if not leaf_hashes or leaf_index < 0 or leaf_index >= len(leaf_hashes):
            raise IndexError(
                f"leaf_index {leaf_index} out of range for {len(leaf_hashes)} leaves"
            )

        if len(leaf_hashes) == 1:
            return []

        proof: list[tuple[str, str]] = []
        level = list(leaf_hashes)
        idx = leaf_index

        while len(level) > 1:
            # Duplicate last if odd
            if len(level) % 2 == 1:
                level.append(level[-1])

            # Determine sibling
            if idx % 2 == 0:
                # Current is left child; sibling is on the right
                sibling = level[idx + 1]
                proof.append((sibling, "right"))
            else:
                # Current is right child; sibling is on the left
                sibling = level[idx - 1]
                proof.append((sibling, "left"))

            # Move up: compute next level and track our index
            next_level: list[str] = []
            for i in range(0, len(level), 2):
                next_level.append(MerkleTree._hash_pair(level[i], level[i + 1]))
            level = next_level
            idx = idx // 2

        return proof

    @staticmethod
    def verify_proof(
        leaf_hash: str, proof: list[tuple[str, str]], root: str
    ) -> bool:
        """Verify a Merkle proof against a known root.

        Args:
            leaf_hash: The hex hash of the leaf being verified.
            proof: List of (sibling_hash, position) tuples from compute_proof.
            root: The expected Merkle root hex hash.

        Returns:
            True if the proof is valid (leaf is included in the tree with
            the given root).
        """
        current = leaf_hash
        for sibling, position in proof:
            if position == "left":
                current = MerkleTree._hash_pair(sibling, current)
            else:
                current = MerkleTree._hash_pair(current, sibling)
        return current == root
