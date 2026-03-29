"""TDD tests for P2 protocol completeness (TODOs 9-12).

TODO-9: Attestation revocation
TODO-10: Commitment reveal/open workflow (already tested in P0, extend here)
TODO-11: Pagination on search/list endpoints
TODO-12: Harden DSN parsing
"""

from __future__ import annotations

import pytest

from products.identity.src.storage import IdentityStorage

# ---------------------------------------------------------------------------
# TODO-9: Attestation revocation
# ---------------------------------------------------------------------------


class TestAttestationRevocation:
    """Attestations should be revocable before expiry."""

    @pytest.mark.asyncio
    async def test_revoke_attestation(self, api):
        """revoke_attestation should mark an attestation as revoked."""
        await api.register_agent("bot-revoke")
        result = await api.submit_metrics("bot-revoke", {"sharpe_30d": 2.0})

        attestations = await api.storage.get_attestations("bot-revoke")
        att_id = await api.storage.get_attestation_id_by_signature(result.attestation.signature)

        revoked = await api.revoke_attestation(att_id, reason="data was incorrect")
        assert revoked["revoked"] is True

        # Should no longer appear in valid attestations
        attestations = await api.storage.get_attestations("bot-revoke", valid_only=True)
        assert len(attestations) == 0

    @pytest.mark.asyncio
    async def test_revoked_attestation_still_in_all(self, api):
        """Revoked attestations should appear when valid_only=False."""
        await api.register_agent("bot-revoke2")
        result = await api.submit_metrics("bot-revoke2", {"sharpe_30d": 3.0})
        att_id = await api.storage.get_attestation_id_by_signature(result.attestation.signature)

        await api.revoke_attestation(att_id, reason="test")

        all_atts = await api.storage.get_attestations("bot-revoke2", valid_only=False)
        assert len(all_atts) == 1

    @pytest.mark.asyncio
    async def test_revoked_claims_excluded(self, api):
        """Claims linked to revoked attestations should not appear in valid claims."""
        await api.register_agent("bot-revoke-claims")
        result = await api.submit_metrics("bot-revoke-claims", {"sharpe_30d": 2.5})
        att_id = await api.storage.get_attestation_id_by_signature(result.attestation.signature)

        # Before revocation
        claims = await api.get_verified_claims("bot-revoke-claims")
        assert len(claims) == 1

        await api.revoke_attestation(att_id, reason="fraud detected")

        # After revocation
        claims = await api.get_verified_claims("bot-revoke-claims")
        assert len(claims) == 0


# ---------------------------------------------------------------------------
# TODO-11: Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    """Search and list endpoints should support offset + limit pagination."""

    @pytest.mark.asyncio
    async def test_search_claims_offset(self, api):
        """search_claims should support offset for pagination."""
        await api.register_agent("bot-page")
        for i in range(5):
            await api.submit_metrics("bot-page", {"sharpe_30d": float(i + 1)})

        # Get first 2
        page1 = await api.storage.search_claims("sharpe_30d", limit=2, offset=0)
        assert len(page1) == 2

        # Get next 2
        page2 = await api.storage.search_claims("sharpe_30d", limit=2, offset=2)
        assert len(page2) == 2

        # Pages should not overlap
        page1_agents = {c.bound_value for c in page1}
        page2_agents = {c.bound_value for c in page2}
        assert page1_agents.isdisjoint(page2_agents)

    @pytest.mark.asyncio
    async def test_get_attestations_offset(self, api):
        """get_attestations should support offset."""
        await api.register_agent("bot-att-page")
        for _ in range(4):
            await api.submit_metrics("bot-att-page", {"sharpe_30d": 2.0})

        page1 = await api.storage.get_attestations("bot-att-page", valid_only=True, limit=2, offset=0)
        assert len(page1) == 2

        page2 = await api.storage.get_attestations("bot-att-page", valid_only=True, limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_get_commitments_offset(self, api):
        """get_commitments should support offset."""
        await api.register_agent("bot-cmt-page")
        for _ in range(3):
            await api.submit_metrics("bot-cmt-page", {"sharpe_30d": 1.5})

        page1 = await api.storage.get_commitments("bot-cmt-page", limit=2, offset=0)
        assert len(page1) == 2

        page2 = await api.storage.get_commitments("bot-cmt-page", limit=2, offset=2)
        assert len(page2) == 1

    @pytest.mark.asyncio
    async def test_get_claim_chains_offset(self, api):
        """get_claim_chains should support offset."""
        await api.register_agent("bot-chain-page")
        for _ in range(3):
            await api.submit_metrics("bot-chain-page", {"sharpe_30d": 2.0})
            await api.build_claim_chain("bot-chain-page")

        page1 = await api.storage.get_claim_chains("bot-chain-page", limit=2, offset=0)
        assert len(page1) == 2

        page2 = await api.storage.get_claim_chains("bot-chain-page", limit=2, offset=2)
        assert len(page2) == 1


# ---------------------------------------------------------------------------
# TODO-12: DSN parsing
# ---------------------------------------------------------------------------


class TestDSNParsing:
    """Storage should handle various DSN formats."""

    @pytest.mark.asyncio
    async def test_memory_dsn(self):
        """':memory:' DSN should create an in-memory database."""
        s = IdentityStorage(dsn=":memory:")
        await s.connect()
        assert s.db is not None
        await s.close()

    @pytest.mark.asyncio
    async def test_sqlite_three_slashes(self, tmp_path):
        """'sqlite:///path' should work (existing format)."""
        s = IdentityStorage(dsn=f"sqlite:///{tmp_path}/test.db")
        await s.connect()
        assert s.db is not None
        await s.close()

    @pytest.mark.asyncio
    async def test_parse_dsn_static_method(self):
        """_parse_dsn should correctly parse various formats."""
        assert IdentityStorage._parse_dsn(":memory:") == ":memory:"
        assert IdentityStorage._parse_dsn("sqlite:///tmp/test.db") == "/tmp/test.db"
        assert IdentityStorage._parse_dsn("sqlite://relative.db") == "relative.db"
        assert IdentityStorage._parse_dsn("/tmp/test.db") == "/tmp/test.db"
        assert IdentityStorage._parse_dsn("test.db") == "test.db"

    @pytest.mark.asyncio
    async def test_bare_path(self, tmp_path):
        """A bare file path should work as DSN."""
        s = IdentityStorage(dsn=f"{tmp_path}/test3.db")
        await s.connect()
        assert s.db is not None
        await s.close()

    @pytest.mark.asyncio
    async def test_unsupported_scheme_raises(self):
        """An unsupported scheme like 'postgres://' should raise ValueError."""
        s = IdentityStorage(dsn="postgres://localhost/identity")
        with pytest.raises(ValueError, match="Unsupported"):
            await s.connect()
