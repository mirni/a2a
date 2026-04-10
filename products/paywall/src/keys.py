"""API key management: create, validate, lookup tier/agent_id.

Key format: a2a_{tier}_{random_hex}
Keys are stored hashed (SHA-256) in SQLite. The plaintext key is only returned once at creation.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any

from .scoping import VALID_SCOPES, KeyScopeError
from .storage import PaywallStorage
from .tiers import TierName, get_tier_config

# Re-export for convenience
__all__ = [
    "InvalidKeyError",
    "ExpiredKeyError",
    "KeyScopeError",
    "KeyManager",
    "_hash_key",
]


class InvalidKeyError(Exception):
    """Raised when an API key is invalid, revoked, or not found."""

    def __init__(self, reason: str = "Invalid API key") -> None:
        self.reason = reason
        super().__init__(reason)


class ExpiredKeyError(InvalidKeyError):
    """Raised when an API key has expired (expires_at < now)."""

    def __init__(self, reason: str = "API key has expired") -> None:
        super().__init__(reason)


def _hash_key(raw_key: str) -> str:
    """SHA-3-256 hash of a raw API key."""
    return hashlib.sha3_256(raw_key.encode()).hexdigest()


def _generate_key(tier: str) -> str:
    """Generate a new API key in format a2a_{tier}_{random_hex}."""
    random_part = secrets.token_hex(12)  # 24 hex chars
    return f"a2a_{tier}_{random_part}"


KEY_ROTATION_GRACE_SECONDS = 300
"""Seconds during which a freshly-revoked key still authenticates.

v1.2.2 audit HIGH-7: key rotation used to immediately invalidate the old
key, making schema probing dangerous. We now keep the old key live for
a short window so clients have time to swap in the new key without an
outage.
"""


@dataclass
class KeyManager:
    """API key lifecycle management."""

    storage: PaywallStorage
    # v1.2.2 audit HIGH-8: the gateway lifespan wires this callback to
    # ``IdentityAPI.register_agent`` so every new key also gets an
    # identity record. The callback must be idempotent — it is invoked
    # with just the ``agent_id`` and is expected to swallow
    # "already exists" errors silently. A raised exception here does
    # not roll back the key creation.
    on_key_created: Any = None

    async def create_key(
        self,
        agent_id: str,
        tier: str | TierName = TierName.FREE,
        connector: str = "",
        scopes: list[str] | None = None,
        allowed_tools: list[str] | None = None,
        allowed_agent_ids: list[str] | None = None,
        expires_at: float | None = None,
    ) -> dict[str, Any]:
        """Create a new API key for an agent.

        Returns a dict with the plaintext key (only time it's available),
        the key hash, agent_id, tier, and scoping fields.

        Validates that the tier is known and scopes are valid before creating.
        """
        if isinstance(tier, TierName):
            tier = tier.value
        # Validate tier name
        get_tier_config(tier)

        # Validate scopes
        scopes_list = scopes if scopes is not None else ["read", "write"]
        if not scopes_list:
            raise ValueError("Scopes must contain at least one scope")
        for s in scopes_list:
            if s not in VALID_SCOPES:
                raise ValueError(f"Invalid scope '{s}'. Valid scopes: {list(VALID_SCOPES)}")

        raw_key = _generate_key(tier)
        key_hash = _hash_key(raw_key)

        record = await self.storage.store_key(
            key_hash=key_hash,
            agent_id=agent_id,
            tier=tier,
            connector=connector,
            allowed_tools=allowed_tools,
            allowed_agent_ids=allowed_agent_ids,
            scopes=scopes_list,
            expires_at=expires_at,
        )

        # v1.2.2 audit HIGH-8: fire the auto-bind callback so the
        # identity record is created alongside the API key. Failures
        # are logged but never propagate — a downstream outage in
        # identity must not block key issuance.
        if self.on_key_created is not None:
            try:
                await self.on_key_created(agent_id)
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger("paywall.keys").warning(
                    "on_key_created hook failed for agent_id=%s",
                    agent_id,
                    exc_info=True,
                )

        return {
            "key": raw_key,
            "key_hash": key_hash,
            "agent_id": agent_id,
            "tier": tier,
            "connector": connector,
            "created_at": record["created_at"],
            "scopes": record["scopes"],
            "allowed_tools": record["allowed_tools"],
            "allowed_agent_ids": record["allowed_agent_ids"],
            "expires_at": record["expires_at"],
        }

    async def validate_key(self, raw_key: str) -> dict[str, Any]:
        """Validate an API key and return its metadata.

        Raises InvalidKeyError if the key is not found or has been revoked.
        Raises ExpiredKeyError if the key has expired.
        """
        if not raw_key or not raw_key.startswith("a2a_"):
            raise InvalidKeyError("Invalid key format")

        key_hash = _hash_key(raw_key)
        record = await self.storage.lookup_key(key_hash)

        if record is None:
            raise InvalidKeyError("API key not found")

        if record["revoked"]:
            # v1.2.2 audit HIGH-7: honor a short grace window after
            # revocation so freshly-rotated clients have time to swap
            # in the new key. The window is only applied if the
            # storage layer recorded a ``revoked_at`` timestamp.
            revoked_at = record.get("revoked_at")
            if revoked_at is not None and (time.time() - float(revoked_at)) < KEY_ROTATION_GRACE_SECONDS:
                grace_remaining = KEY_ROTATION_GRACE_SECONDS - (time.time() - float(revoked_at))
                record["_key_grace_seconds_remaining"] = int(grace_remaining)
            else:
                raise InvalidKeyError("API key has been revoked")

        # Check expiration
        if record.get("expires_at") is not None and record["expires_at"] < time.time():
            raise ExpiredKeyError("API key has expired")

        # #21: Key age warning (90 days)
        created = record.get("created_at")
        if created is not None:
            age_days = (time.time() - created) / 86400
            if age_days > 90:
                record["_key_age_warning"] = f"Key is {int(age_days)} days old. Consider rotating."

        return record

    async def revoke_key(self, raw_key: str) -> bool:
        """Revoke an API key. Returns True if successfully revoked.

        Also records the revocation timestamp (revoked_at).
        """
        key_hash = _hash_key(raw_key)
        return await self.storage.revoke_key(key_hash)

    async def get_agent_keys(self, agent_id: str) -> list[dict[str, Any]]:
        """List all keys (active and revoked) for an agent."""
        return await self.storage.get_keys_for_agent(agent_id)

    async def lookup_agent(self, raw_key: str) -> tuple[str, str]:
        """Convenience: validate a key and return (agent_id, tier).

        Raises InvalidKeyError on failure.
        """
        record = await self.validate_key(raw_key)
        return record["agent_id"], record["tier"]
