"""Tests for message-level encryption — MessageCrypto and MessagingAPI integration.

Covers:
- Round-trip encrypt/decrypt
- Encrypted body stored as ciphertext (not readable)
- Wrong key fails decryption
- Unique nonce per message
- send_message with encrypt=True stores encrypted body
- Backward compatibility (unencrypted messages still work)
- encryption_metadata contains required fields
- Negative: encrypt with missing recipient key raises error
"""

from __future__ import annotations

import base64
import os
import sys
import types

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Path / module setup (mirrors conftest.py)
# ---------------------------------------------------------------------------
_shared_src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "shared", "src"))
if "shared_src" not in sys.modules:
    _pkg = types.ModuleType("shared_src")
    _pkg.__path__ = [_shared_src_dir]
    _pkg.__package__ = "shared_src"
    sys.modules["shared_src"] = _pkg

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
for p in [_project_root]:
    if p not in sys.path:
        sys.path.insert(0, p)

from products.identity.src.crypto import AgentCrypto
from products.messaging.src.api import MessagingAPI
from products.messaging.src.crypto import MessageCrypto
from products.messaging.src.models import EncryptionMetadata, Message, MessageType
from products.messaging.src.storage import MessageStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def storage(tmp_path):
    dsn = f"sqlite:///{tmp_path}/messaging_enc_test.db"
    s = MessageStorage(dsn=dsn)
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def api(storage):
    return MessagingAPI(storage=storage)


@pytest.fixture
def alice_keys():
    """Generate an Ed25519 keypair for Alice.

    Returns (ed25519_private_hex, ed25519_public_hex, x25519_public_hex).
    The x25519 public key is derived from the Ed25519 private seed.
    """
    priv, pub = AgentCrypto.generate_keypair()
    x25519_pub = MessageCrypto.x25519_public_key_from_ed25519_private(priv)
    return priv, pub, x25519_pub


@pytest.fixture
def bob_keys():
    """Generate an Ed25519 keypair for Bob.

    Returns (ed25519_private_hex, ed25519_public_hex, x25519_public_hex).
    """
    priv, pub = AgentCrypto.generate_keypair()
    x25519_pub = MessageCrypto.x25519_public_key_from_ed25519_private(priv)
    return priv, pub, x25519_pub


# ===========================================================================
# MessageCrypto unit tests
# ===========================================================================


class TestMessageCryptoRoundTrip:
    """Encrypt then decrypt must return original plaintext."""

    def test_encrypt_decrypt_round_trip(self, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys
        plaintext = "Hello Bob, this is a secret message."

        ciphertext, nonce, ephemeral_pub = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )

        # Decrypt using Bob's private key and the ephemeral public key
        decrypted = MessageCrypto.decrypt_message(
            recipient_private_key_hex=bob_priv,
            sender_public_key_hex=ephemeral_pub,
            ciphertext=ciphertext,
            nonce=nonce,
        )

        assert decrypted == plaintext

    def test_encrypted_body_is_not_plaintext(self, alice_keys, bob_keys):
        """The ciphertext must not contain the plaintext."""
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys
        plaintext = "This should be hidden after encryption."

        ciphertext, _, _ = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )

        # ciphertext is base64-encoded; decode and check plaintext isn't in there
        assert plaintext not in ciphertext
        assert plaintext.encode() not in base64.b64decode(ciphertext)


class TestDecryptionWithWrongKey:
    """Decryption with an unrelated private key must fail."""

    def test_wrong_recipient_key_fails(self, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys
        plaintext = "Secret for Bob only."

        ciphertext, nonce, ephemeral_pub = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )

        # Charlie generates a completely different key
        charlie_priv, _ = AgentCrypto.generate_keypair()

        with pytest.raises(Exception):
            # Using Charlie's private key must fail
            MessageCrypto.decrypt_message(
                recipient_private_key_hex=charlie_priv,
                sender_public_key_hex=ephemeral_pub,
                ciphertext=ciphertext,
                nonce=nonce,
            )


class TestUniqueNonce:
    """Each encryption must produce a unique nonce."""

    def test_nonces_are_unique(self, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys
        plaintext = "Same plaintext both times."

        _, nonce1, _ = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )
        _, nonce2, _ = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )

        assert nonce1 != nonce2


class TestEncryptionMetadataFields:
    """encryption_metadata dict must contain nonce, algo, ephemeral_public_key."""

    def test_encrypt_returns_all_metadata_components(self, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys

        ciphertext, nonce, ephemeral_pub = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext="metadata check",
        )

        # All three must be non-empty strings
        assert len(ciphertext) > 0
        assert len(nonce) > 0
        assert len(ephemeral_pub) > 0

        # Must be valid base64 (ciphertext and nonce)
        base64.b64decode(ciphertext)
        base64.b64decode(nonce)
        # ephemeral_pub is hex
        bytes.fromhex(ephemeral_pub)


# ===========================================================================
# EncryptionMetadata model tests
# ===========================================================================


class TestEncryptionMetadataModel:
    """EncryptionMetadata Pydantic model must enforce required fields and have schema_extra."""

    def test_encryption_metadata_creation(self):
        meta = EncryptionMetadata(
            nonce="dGVzdG5vbmNl",
            algorithm="x25519-aes256gcm",
            ephemeral_public_key="ab" * 32,
        )
        assert meta.nonce == "dGVzdG5vbmNl"
        assert meta.algorithm == "x25519-aes256gcm"
        assert meta.ephemeral_public_key == "ab" * 32

    def test_encryption_metadata_schema_extra(self):
        """Model must have json_schema_extra examples (CLAUDE.md requirement)."""
        schema = EncryptionMetadata.model_json_schema()
        assert "examples" in schema or "example" in schema or any(
            "examples" in str(v) for v in schema.values()
        )


# ===========================================================================
# Message model with encryption fields
# ===========================================================================


class TestMessageEncryptionFields:
    """Message model must support `encrypted` and `encryption_metadata` fields."""

    def test_message_encrypted_default_false(self):
        msg = Message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body="hello",
        )
        assert msg.encrypted is False
        assert msg.encryption_metadata is None

    def test_message_encrypted_true_with_metadata(self):
        meta = EncryptionMetadata(
            nonce="dGVzdG5vbmNl",
            algorithm="x25519-aes256gcm",
            ephemeral_public_key="ab" * 32,
        )
        msg = Message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body="base64ciphertext==",
            encrypted=True,
            encryption_metadata=meta,
        )
        assert msg.encrypted is True
        assert msg.encryption_metadata is not None
        assert msg.encryption_metadata.algorithm == "x25519-aes256gcm"


# ===========================================================================
# MessagingAPI integration tests
# ===========================================================================


class TestSendMessageEncrypted:
    """send_message with encrypt=True must encrypt the body and store metadata."""

    async def test_send_encrypted_message(self, api, storage, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys
        plaintext = "Top secret negotiation details."

        msg = await api.send_message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body=plaintext,
            encrypt=True,
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
        )

        # The stored body must not be the plaintext
        assert msg.encrypted is True
        assert msg.body != plaintext
        assert msg.encryption_metadata is not None
        assert msg.encryption_metadata.nonce
        assert msg.encryption_metadata.algorithm == "x25519-aes256gcm"
        assert msg.encryption_metadata.ephemeral_public_key

    async def test_encrypted_body_in_storage(self, api, storage, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys
        plaintext = "Storage level check."

        await api.send_message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body=plaintext,
            encrypt=True,
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
        )

        # Read directly from storage
        msgs = await storage.get_messages("bob")
        assert len(msgs) == 1
        stored_body = msgs[0]["body"]
        assert stored_body != plaintext
        # Verify it's base64 encoded ciphertext
        base64.b64decode(stored_body)


class TestSendMessageUnencrypted:
    """Backward compatibility: default encrypt=False must store plaintext."""

    async def test_unencrypted_message_stores_plaintext(self, api, storage):
        plaintext = "Public message."

        msg = await api.send_message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body=plaintext,
        )

        assert msg.encrypted is False
        assert msg.body == plaintext
        assert msg.encryption_metadata is None

        msgs = await storage.get_messages("bob")
        assert msgs[0]["body"] == plaintext


class TestGetMessagesDecryption:
    """get_messages with decrypt_key should decrypt on retrieval."""

    async def test_get_messages_with_decrypt_key(self, api, storage, alice_keys, bob_keys):
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys
        plaintext = "Decrypt me on retrieval."

        await api.send_message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body=plaintext,
            encrypt=True,
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
        )

        # Decrypt on retrieval using Bob's Ed25519 private key
        # The ephemeral public key is in the encryption_metadata
        msgs = await api.get_messages(
            "bob",
            decrypt_key=bob_priv,
        )
        assert len(msgs) == 1
        assert msgs[0]["body"] == plaintext

    async def test_get_messages_without_decrypt_key_returns_ciphertext(
        self, api, storage, alice_keys, bob_keys
    ):
        alice_priv, _, _ = alice_keys
        _, _, bob_x25519_pub = bob_keys
        plaintext = "Should stay encrypted."

        await api.send_message(
            sender="alice",
            recipient="bob",
            message_type=MessageType.TEXT,
            body=plaintext,
            encrypt=True,
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
        )

        msgs = await api.get_messages("bob")
        assert len(msgs) == 1
        assert msgs[0]["body"] != plaintext


# ===========================================================================
# Negative tests
# ===========================================================================


class TestEncryptionNegativeCases:
    """Negative tests for encryption edge cases."""

    def test_encrypt_with_empty_plaintext(self, alice_keys, bob_keys):
        """Empty string should encrypt/decrypt correctly."""
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys

        ciphertext, nonce, eph = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext="",
        )

        decrypted = MessageCrypto.decrypt_message(
            recipient_private_key_hex=bob_priv,
            sender_public_key_hex=eph,
            ciphertext=ciphertext,
            nonce=nonce,
        )
        assert decrypted == ""

    def test_encrypt_with_unicode_plaintext(self, alice_keys, bob_keys):
        """Unicode message must round-trip correctly."""
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys
        plaintext = "Price: 100.50 EUR. Shipping to Munchen."

        ciphertext, nonce, eph = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext=plaintext,
        )

        decrypted = MessageCrypto.decrypt_message(
            recipient_private_key_hex=bob_priv,
            sender_public_key_hex=eph,
            ciphertext=ciphertext,
            nonce=nonce,
        )
        assert decrypted == plaintext

    def test_tampered_ciphertext_fails(self, alice_keys, bob_keys):
        """Modifying ciphertext must cause decryption to fail (authenticated encryption)."""
        alice_priv, _, _ = alice_keys
        bob_priv, _, bob_x25519_pub = bob_keys

        ciphertext, nonce, eph = MessageCrypto.encrypt_message(
            sender_private_key_hex=alice_priv,
            recipient_public_key_hex=bob_x25519_pub,
            plaintext="Integrity test.",
        )

        # Tamper with ciphertext
        raw = base64.b64decode(ciphertext)
        tampered = bytes([raw[0] ^ 0xFF]) + raw[1:]
        tampered_b64 = base64.b64encode(tampered).decode()

        with pytest.raises(Exception):
            MessageCrypto.decrypt_message(
                recipient_private_key_hex=bob_priv,
                sender_public_key_hex=eph,
                ciphertext=tampered_b64,
                nonce=nonce,
            )

    async def test_send_encrypted_without_keys_raises(self, api):
        """Calling encrypt=True without keys must raise ValueError."""
        with pytest.raises(ValueError, match="sender_private_key_hex.*required"):
            await api.send_message(
                sender="alice",
                recipient="bob",
                message_type=MessageType.TEXT,
                body="This should fail",
                encrypt=True,
            )

    def test_invalid_recipient_key_hex_raises(self):
        """Invalid hex for recipient public key must raise an error."""
        alice_priv, _ = AgentCrypto.generate_keypair()
        with pytest.raises(Exception):
            MessageCrypto.encrypt_message(
                sender_private_key_hex=alice_priv,
                recipient_public_key_hex="not_valid_hex",
                plaintext="test",
            )

    def test_invalid_recipient_key_wrong_length_raises(self):
        """Recipient public key with wrong length must raise an error."""
        alice_priv, _ = AgentCrypto.generate_keypair()
        with pytest.raises(Exception):
            MessageCrypto.encrypt_message(
                sender_private_key_hex=alice_priv,
                recipient_public_key_hex="ab" * 16,  # 16 bytes, need 32
                plaintext="test",
            )
