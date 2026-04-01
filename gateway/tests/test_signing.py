"""Tests for gateway.src.signing — HMAC-SHA3-256 fallback + dilithium mock paths."""

from __future__ import annotations

from unittest.mock import MagicMock

from gateway.src.signing import SigningManager, sign_response

# ---------------------------------------------------------------------------
# HMAC path tests (dilithium not available — default in CI)
# ---------------------------------------------------------------------------


class TestHMACPath:
    def test_sign_returns_hex_string(self):
        mgr = SigningManager()
        sig = mgr.sign(b"hello world")

        assert sig is not None
        assert isinstance(sig, str)
        bytes.fromhex(sig)  # must be valid hex

    def test_verify_correct_signature(self):
        mgr = SigningManager()
        sig = mgr.sign(b"test data")

        assert mgr.verify(b"test data", sig) is True

    def test_verify_wrong_signature(self):
        mgr = SigningManager()
        mgr.sign(b"test data")

        assert mgr.verify(b"test data", "deadbeef" * 8) is False

    def test_verify_malformed_hex(self):
        mgr = SigningManager()

        # Non-hex string should return False, not raise
        assert mgr.verify(b"test data", "not-valid-hex!!!") is False

    def test_get_public_key_returns_hex(self):
        mgr = SigningManager()
        pk = mgr.get_public_key()

        assert pk is not None
        assert isinstance(pk, str)
        assert len(bytes.fromhex(pk)) == 32  # 32-byte key

    def test_available_is_true(self):
        mgr = SigningManager()
        assert mgr.available is True


# ---------------------------------------------------------------------------
# sign_response helper
# ---------------------------------------------------------------------------


class TestSignResponse:
    def test_returns_header_dict(self):
        mgr = SigningManager()
        headers = sign_response(mgr, b'{"result": "ok"}')

        assert "X-A2A-Signature-Dilithium" in headers
        bytes.fromhex(headers["X-A2A-Signature-Dilithium"])

    def test_unavailable_returns_empty(self):
        mgr = SigningManager()
        mgr.available = False
        headers = sign_response(mgr, b'{"result": "ok"}')

        assert headers == {}


# ---------------------------------------------------------------------------
# Dilithium mock paths
# ---------------------------------------------------------------------------


class TestDilithiumPaths:
    def test_keygen_failure_falls_back_to_hmac(self):
        """If dilithium.keygen() raises, manager falls back to HMAC."""
        mock_mod = MagicMock()
        mock_mod.keygen.side_effect = RuntimeError("keygen boom")

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            assert mgr.available is True
            assert mgr._hmac_key is not None
            assert mgr._dilithium_sk is None
        finally:
            signing_mod._dilithium_mod = original

    def test_dilithium_sign_failure_returns_none(self):
        """If dilithium.sign() raises, sign() returns None."""
        mock_mod = MagicMock()
        mock_mod.keygen.return_value = (b"pk", b"sk")
        mock_mod.sign.side_effect = RuntimeError("sign boom")

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            assert mgr._is_dilithium() is True
            assert mgr.sign(b"data") is None
        finally:
            signing_mod._dilithium_mod = original

    def test_dilithium_verify_failure_returns_false(self):
        """If dilithium.verify() raises, verify() returns False."""
        mock_mod = MagicMock()
        mock_mod.keygen.return_value = (b"pk", b"sk")
        mock_mod.verify.side_effect = RuntimeError("verify boom")

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            assert mgr.verify(b"data", "aabb") is False
        finally:
            signing_mod._dilithium_mod = original

    def test_dilithium_sign_returns_hex(self):
        """Happy path: dilithium.sign() returns bytes, we get hex."""
        mock_mod = MagicMock()
        mock_mod.keygen.return_value = (b"pk", b"sk")
        mock_mod.sign.return_value = b"\xde\xad\xbe\xef"

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            sig = mgr.sign(b"data")
            assert sig == "deadbeef"
        finally:
            signing_mod._dilithium_mod = original

    def test_dilithium_get_public_key_returns_hex(self):
        """Happy path: get_public_key returns hex of pk bytes."""
        mock_mod = MagicMock()
        mock_mod.keygen.return_value = (b"\xca\xfe", b"sk")

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            pk = mgr.get_public_key()
            assert pk == "cafe"
        finally:
            signing_mod._dilithium_mod = original

    def test_dilithium_get_public_key_failure_returns_none(self):
        """If converting pk to bytes raises, get_public_key returns None."""
        mock_mod = MagicMock()
        # keygen returns a non-bytes pk that will fail bytes() and .hex()
        bad_pk = object()  # not bytes, bytes() will raise TypeError

        mock_mod.keygen.return_value = (bad_pk, b"sk")

        import gateway.src.signing as signing_mod

        original = signing_mod._dilithium_mod
        try:
            signing_mod._dilithium_mod = mock_mod
            mgr = SigningManager()

            pk = mgr.get_public_key()
            assert pk is None
        finally:
            signing_mod._dilithium_mod = original
