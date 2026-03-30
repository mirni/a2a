"""Message-level encryption using X25519 key exchange and AES-256-GCM.

Provides end-to-end encryption for agent-to-agent messages. The sender's
Ed25519 private key is converted to an X25519 key for Diffie-Hellman key
exchange; the shared secret is used to derive an AES-256-GCM key.

Each message gets a unique random nonce to prevent ciphertext reuse.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

# AES-256-GCM nonce size: 12 bytes (96 bits), recommended by NIST SP 800-38D
_NONCE_SIZE = 12

# Algorithm identifier stored in encryption metadata
ALGORITHM = "x25519-aes256gcm"


class MessageCrypto:
    """Stateless message encryption/decryption using X25519 + AES-256-GCM."""

    @staticmethod
    def _ed25519_hex_to_x25519_private(ed25519_private_hex: str) -> X25519PrivateKey:
        """Convert Ed25519 raw private key (hex) to X25519 private key.

        The 32-byte Ed25519 seed is used directly as the X25519 private scalar.
        The `cryptography` library applies RFC 7748 clamping internally.
        """
        raw = bytes.fromhex(ed25519_private_hex)
        return X25519PrivateKey.from_private_bytes(raw)

    @staticmethod
    def encrypt_message(
        sender_private_key_hex: str,
        recipient_public_key_hex: str,
        plaintext: str,
    ) -> tuple[str, str, str]:
        """Encrypt a message using ephemeral X25519 ECDH + AES-256-GCM.

        An ephemeral X25519 keypair is generated for each message, providing
        forward secrecy. The shared secret is derived via ECDH between the
        ephemeral private key and the recipient's X25519 public key.

        Args:
            sender_private_key_hex: Sender's Ed25519 private key as hex.
                Reserved for future use (e.g. authenticated encryption).
            recipient_public_key_hex: Recipient's X25519 public key as hex.
                Callers should derive this from the recipient's Ed25519 seed
                using ``x25519_public_key_from_ed25519_private()``.
            plaintext: The message body to encrypt.

        Returns:
            Tuple of (ciphertext_b64, nonce_b64, ephemeral_public_key_hex):
            - ciphertext_b64: Base64-encoded AES-256-GCM ciphertext.
            - nonce_b64: Base64-encoded 12-byte nonce.
            - ephemeral_public_key_hex: Hex-encoded ephemeral X25519 public key
              (needed by recipient for decryption).
        """
        # Generate ephemeral X25519 keypair for forward secrecy
        ephemeral_private = X25519PrivateKey.generate()
        ephemeral_public = ephemeral_private.public_key()
        ephemeral_public_hex = ephemeral_public.public_bytes(
            Encoding.Raw, PublicFormat.Raw
        ).hex()

        # Parse recipient's precomputed X25519 public key
        recipient_x25519_pub = X25519PublicKey.from_public_bytes(
            bytes.fromhex(recipient_public_key_hex)
        )

        # ECDH: ephemeral private * recipient public -> shared secret
        shared_secret = ephemeral_private.exchange(recipient_x25519_pub)

        # Derive AES-256 key from shared secret via SHA-256
        aes_key = hashlib.sha256(shared_secret).digest()

        # Encrypt with AES-256-GCM
        nonce = os.urandom(_NONCE_SIZE)
        aead = AESGCM(aes_key)
        ciphertext = aead.encrypt(nonce, plaintext.encode("utf-8"), None)

        return (
            base64.b64encode(ciphertext).decode("ascii"),
            base64.b64encode(nonce).decode("ascii"),
            ephemeral_public_hex,
        )

    @staticmethod
    def decrypt_message(
        recipient_private_key_hex: str,
        sender_public_key_hex: str,
        ciphertext: str,
        nonce: str,
    ) -> str:
        """Decrypt a message using X25519 ECDH + AES-256-GCM.

        The recipient derives their X25519 private key from their Ed25519 seed,
        then performs ECDH with the sender's ephemeral X25519 public key
        (transmitted in `sender_public_key_hex`, which is actually the
        ephemeral public key).

        Args:
            recipient_private_key_hex: Recipient's Ed25519 private key as hex.
            sender_public_key_hex: The ephemeral X25519 public key from the
                message metadata (hex-encoded).
            ciphertext: Base64-encoded AES-256-GCM ciphertext.
            nonce: Base64-encoded 12-byte nonce.

        Returns:
            Decrypted plaintext string.

        Raises:
            cryptography.exceptions.InvalidTag: If decryption fails (wrong key
                or tampered ciphertext).
        """
        # Derive recipient's X25519 private key from Ed25519 seed
        recipient_x25519_priv = MessageCrypto._ed25519_hex_to_x25519_private(
            recipient_private_key_hex
        )

        # The sender_public_key_hex is the ephemeral X25519 public key
        ephemeral_pub = X25519PublicKey.from_public_bytes(
            bytes.fromhex(sender_public_key_hex)
        )

        # ECDH: recipient private * ephemeral public -> shared secret
        shared_secret = recipient_x25519_priv.exchange(ephemeral_pub)

        # Derive same AES-256 key
        aes_key = hashlib.sha256(shared_secret).digest()

        # Decrypt
        nonce_bytes = base64.b64decode(nonce)
        ciphertext_bytes = base64.b64decode(ciphertext)
        aead = AESGCM(aes_key)
        plaintext_bytes = aead.decrypt(nonce_bytes, ciphertext_bytes, None)

        return plaintext_bytes.decode("utf-8")

    @staticmethod
    def x25519_public_key_from_ed25519_private(ed25519_private_hex: str) -> str:
        """Derive the X25519 public key hex from an Ed25519 private key (seed).

        This is used to compute the recipient's X25519 public key for encryption
        when only their Ed25519 private key seed is known (at registration time).

        Args:
            ed25519_private_hex: Ed25519 private key seed as hex.

        Returns:
            X25519 public key as hex string.
        """
        x_priv = MessageCrypto._ed25519_hex_to_x25519_private(ed25519_private_hex)
        x_pub = x_priv.public_key()
        return x_pub.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
