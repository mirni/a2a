"""Tests for sub-identity support (TDD).

Sub-identities let a single agent operate as multiple personas/roles.
"""

from __future__ import annotations

import pytest

from products.identity.src.api import IdentityAPI

pytestmark = pytest.mark.asyncio


class TestCreateSubIdentity:
    """Test creating sub-identities."""

    async def test_create_sub_identity(self, api: IdentityAPI):
        await api.register_agent("parent-agent")
        sub = await api.create_sub_identity("parent-agent", "analyzer")
        assert sub.parent_agent_id == "parent-agent"
        assert sub.role_name == "analyzer"
        assert sub.sub_identity_id is not None

    async def test_sub_identity_gets_own_keypair(self, api: IdentityAPI):
        await api.register_agent("parent-kp")
        sub = await api.create_sub_identity("parent-kp", "worker")
        assert sub.public_key is not None
        assert len(sub.public_key) > 0

    async def test_create_with_custom_key(self, api: IdentityAPI):
        from products.identity.src.crypto import AgentCrypto

        crypto = AgentCrypto()
        pub, _priv = crypto.generate_keypair()

        await api.register_agent("parent-ck")
        sub = await api.create_sub_identity("parent-ck", "signer", public_key=pub)
        assert sub.public_key == pub

    async def test_create_for_nonexistent_parent(self, api: IdentityAPI):
        from products.identity.src.api import AgentNotFoundError

        with pytest.raises(AgentNotFoundError):
            await api.create_sub_identity("no-such-agent", "role")

    async def test_duplicate_role_rejected(self, api: IdentityAPI):
        await api.register_agent("parent-dup")
        await api.create_sub_identity("parent-dup", "analyzer")
        with pytest.raises(ValueError, match="already exists"):
            await api.create_sub_identity("parent-dup", "analyzer")

    async def test_create_with_metadata(self, api: IdentityAPI):
        await api.register_agent("parent-meta")
        sub = await api.create_sub_identity(
            "parent-meta",
            "specialist",
            metadata={"department": "data", "level": "senior"},
        )
        assert sub.metadata["department"] == "data"


class TestGetSubIdentity:
    """Test retrieving sub-identities."""

    async def test_get_sub_identity(self, api: IdentityAPI):
        await api.register_agent("parent-get")
        created = await api.create_sub_identity("parent-get", "reader")
        fetched = await api.get_sub_identity(created.sub_identity_id)
        assert fetched is not None
        assert fetched.role_name == "reader"
        assert fetched.parent_agent_id == "parent-get"

    async def test_get_nonexistent_returns_none(self, api: IdentityAPI):
        result = await api.get_sub_identity("sub-nonexistent")
        assert result is None


class TestListSubIdentities:
    """Test listing sub-identities for a parent agent."""

    async def test_list_sub_identities(self, api: IdentityAPI):
        await api.register_agent("parent-list")
        await api.create_sub_identity("parent-list", "reader")
        await api.create_sub_identity("parent-list", "writer")
        await api.create_sub_identity("parent-list", "admin")

        subs = await api.list_sub_identities("parent-list")
        assert len(subs) == 3
        roles = {s.role_name for s in subs}
        assert roles == {"reader", "writer", "admin"}

    async def test_list_empty(self, api: IdentityAPI):
        await api.register_agent("parent-empty")
        subs = await api.list_sub_identities("parent-empty")
        assert subs == []


class TestDeleteSubIdentity:
    """Test deleting sub-identities."""

    async def test_delete_sub_identity(self, api: IdentityAPI):
        await api.register_agent("parent-del")
        sub = await api.create_sub_identity("parent-del", "temp")
        await api.delete_sub_identity(sub.sub_identity_id)
        result = await api.get_sub_identity(sub.sub_identity_id)
        assert result is None

    async def test_delete_nonexistent_is_noop(self, api: IdentityAPI):
        # Should not raise
        await api.delete_sub_identity("sub-nonexistent")
