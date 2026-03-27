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
