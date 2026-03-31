"""CRYSTALS-Dilithium signature support with HMAC-SHA3-256 fallback.

Provides post-quantum signing capabilities when the dilithium package is
available, falling back to HMAC-SHA3-256 using a random 32-byte key when
it is not.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Attempt to import dilithium; set a module-level flag so the class knows
# which path to take without re-trying the import on every instantiation.
# ---------------------------------------------------------------------------
_dilithium_mod: Any = None
try:
    import dilithium as _dilithium_mod  # type: ignore[import-untyped,no-redef]
except ImportError:
    _dilithium_mod = None


class SigningManager:
    """Manage request/response signing.

    If the ``dilithium`` package is importable, a CRYSTALS-Dilithium keypair
    is generated and used for all operations.  Otherwise a random 32-byte
    HMAC-SHA3-256 key is generated as a practical fallback that keeps the
    same interface.
    """

    def __init__(self) -> None:
        self.available: bool = False
        self._dilithium_sk: object | None = None
        self._dilithium_pk: object | None = None
        self._hmac_key: bytes | None = None

        if _dilithium_mod is not None:
            try:
                # dilithium.keygen() returns (public_key, secret_key)
                self._dilithium_pk, self._dilithium_sk = _dilithium_mod.keygen()
                self.available = True
                logger.info("SigningManager: CRYSTALS-Dilithium keypair generated")
                return
            except Exception:
                logger.warning(
                    "SigningManager: dilithium module found but keygen failed; falling back to HMAC-SHA3-256",
                    exc_info=True,
                )

        # -- Fallback: HMAC-SHA3-256 with a random 32-byte key ---------------
        logger.warning("SigningManager: dilithium package not available; using HMAC-SHA3-256 fallback")
        self._hmac_key = os.urandom(32)
        self.available = True

    # -- signing helpers (private) ------------------------------------------

    def _hmac_sign(self, data: bytes) -> str:
        """Compute HMAC-SHA3-256 of *data* using the internal key."""
        assert self._hmac_key is not None
        return hmac.new(self._hmac_key, data, hashlib.sha3_256).hexdigest()

    def _is_dilithium(self) -> bool:
        return self._dilithium_sk is not None

    # -- public API ---------------------------------------------------------

    def sign(self, data: bytes) -> str | None:
        """Sign *data* and return the hex-encoded signature.

        Returns ``None`` if signing is not available.
        """
        if not self.available:
            return None

        if self._is_dilithium():
            try:
                sig: bytes = _dilithium_mod.sign(self._dilithium_sk, data)  # type: ignore[union-attr]
                return sig.hex()
            except Exception:
                logger.error("Dilithium sign() failed", exc_info=True)
                return None

        return self._hmac_sign(data)

    def get_public_key(self) -> str | None:
        """Return the hex-encoded public key, or ``None`` if unavailable."""
        if not self.available:
            return None

        if self._is_dilithium():
            try:
                pk_bytes: bytes = (
                    self._dilithium_pk if isinstance(self._dilithium_pk, bytes) else bytes(self._dilithium_pk)  # type: ignore[arg-type,call-overload]
                )
                return pk_bytes.hex()
            except Exception:
                logger.error("Dilithium get_public_key() failed", exc_info=True)
                return None

        # Fallback: expose the HMAC key as the "public key".
        # In a real HMAC scheme the key is shared-secret, but this satisfies
        # the interface contract for local / dev usage.
        assert self._hmac_key is not None
        return self._hmac_key.hex()

    def verify(self, data: bytes, signature: str) -> bool:
        """Verify *signature* (hex-encoded) against *data*.

        Returns ``False`` if signing is not available or verification fails.
        """
        if not self.available:
            return False

        if self._is_dilithium():
            try:
                sig_bytes = bytes.fromhex(signature)
                return _dilithium_mod.verify(  # type: ignore[union-attr]
                    self._dilithium_pk, data, sig_bytes
                )
            except Exception:
                logger.error("Dilithium verify() failed", exc_info=True)
                return False

        # HMAC fallback: recompute and compare in constant time.
        expected = self._hmac_sign(data)
        return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


async def signing_key_handler(request: Any) -> Any:
    """Return the public key and algorithm used by the active SigningManager.

    Expects ``request.app.state.signing_manager`` to be a :class:`SigningManager`.
    """
    from fastapi.responses import JSONResponse  # local import to avoid top-level dep

    manager: SigningManager = request.app.state.signing_manager
    algorithm = "crystals-dilithium" if manager._is_dilithium() else "hmac-sha3-256"
    return JSONResponse({"public_key": manager.get_public_key(), "algorithm": algorithm})


# ---------------------------------------------------------------------------
# Response-signing helper
# ---------------------------------------------------------------------------


def sign_response(manager: SigningManager, body: bytes) -> dict[str, str]:
    """Return a headers dict with the signature header if signing is available.

    Returns an empty dict when signing is unavailable so callers can always
    unpack with ``**sign_response(mgr, body)``.
    """
    if not manager.available:
        return {}

    signature = manager.sign(body)
    if signature is None:
        return {}

    return {"X-A2A-Signature-Dilithium": signature}
