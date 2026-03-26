"""API key management: create, validate, lookup tier/agent_id.

Key format: a2a_{tier}_{random_hex}
Keys are stored hashed (SHA-256) in SQLite. The plaintext key is only returned once at creation.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from .storage import PaywallStorage
from .tiers import TierName, get_tier_config


class InvalidKeyError(Exception):
    """Raised when an API key is invalid, revoked, or not found."""

    def __init__(self, reason: str = "Invalid API key") -> None:
        self.reason = reason
        super().__init__(reason)


def _hash_key(raw_key: str) -> str:
    """SHA-3-256 hash of a raw API key."""
    return hashlib.sha3_256(raw_key.encode()).hexdigest()


def _generate_key(tier: str) -> str:
    """Generate a new API key in format a2a_{tier}_{random_hex}."""
    random_part = secrets.token_hex(12)  # 24 hex chars
    return f"a2a_{tier}_{random_part}"


@dataclass
class KeyManager:
    """API key lifecycle management."""

    storage: PaywallStorage

    async def create_key(
        self,
        agent_id: str,
        tier: str | TierName = TierName.FREE,
        connector: str = "",
    ) -> dict[str, Any]:
        """Create a new API key for an agent.

        Returns a dict with the plaintext key (only time it's available),
        the key hash, agent_id, and tier.

        Validates that the tier is known before creating.
        """
        if isinstance(tier, TierName):
            tier = tier.value
        # Validate tier name
        get_tier_config(tier)

        raw_key = _generate_key(tier)
        key_hash = _hash_key(raw_key)

        record = await self.storage.store_key(
            key_hash=key_hash,
            agent_id=agent_id,
            tier=tier,
            connector=connector,
        )

        return {
            "key": raw_key,
            "key_hash": key_hash,
            "agent_id": agent_id,
            "tier": tier,
            "connector": connector,
            "created_at": record["created_at"],
        }

    async def validate_key(self, raw_key: str) -> dict[str, Any]:
        """Validate an API key and return its metadata.

        Raises InvalidKeyError if the key is not found or has been revoked.
        """
        if not raw_key or not raw_key.startswith("a2a_"):
            raise InvalidKeyError("Invalid key format")

        key_hash = _hash_key(raw_key)
        record = await self.storage.lookup_key(key_hash)

        if record is None:
            raise InvalidKeyError("API key not found")

        if record["revoked"]:
            raise InvalidKeyError("API key has been revoked")

        return record

    async def revoke_key(self, raw_key: str) -> bool:
        """Revoke an API key. Returns True if successfully revoked."""
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
