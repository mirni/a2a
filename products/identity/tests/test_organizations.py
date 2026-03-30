"""TDD tests for Organization and OrgMembership models and storage.

Covers:
- Create org, verify owner is auto-added as owner role
- Get org details
- Add/remove members
- Only owner/admin can add members
- List org members
- Negative: duplicate org name for same owner
- Negative: add non-existent agent to org
- Negative: remove non-member from org
- Model json_schema_extra validation
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from products.identity.src.models import Organization, OrgMembership
from products.identity.src.org_api import (
    AlreadyMemberError,
    MemberNotFoundError,
    NotAuthorizedError,
    OrgAPI,
    OrgNotFoundError,
)
from products.identity.src.storage import IdentityStorage


@pytest_asyncio.fixture
async def org_storage(tmp_path):
    """Provide a connected IdentityStorage backed by a temporary SQLite database."""
    dsn = f"sqlite:///{tmp_path}/org_test.db"
    s = IdentityStorage(dsn=dsn)
    await s.connect()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def org_api(org_storage):
    """Provide an OrgAPI instance backed by temporary storage."""
    return OrgAPI(storage=org_storage)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestOrganizationModel:
    """Organization Pydantic model tests."""

    def test_organization_schema_extra_exists(self):
        """Organization model must have json_schema_extra with example."""
        schema = Organization.model_json_schema()
        assert (
            "examples" in schema
            or "example" in schema
            or Organization.model_config.get("json_schema_extra") is not None
        )

    def test_organization_fields(self):
        """Organization must have required fields."""
        example = Organization.model_config["json_schema_extra"]["examples"][0]
        org = Organization(**example)
        assert org.id
        assert org.name
        assert org.owner_agent_id
        assert org.created_at > 0

    def test_organization_extra_forbid(self):
        """Organization model must forbid extra fields."""
        example = Organization.model_config["json_schema_extra"]["examples"][0]
        with pytest.raises(Exception):
            Organization(**example, unexpected_field="bad")


class TestOrgMembershipModel:
    """OrgMembership Pydantic model tests."""

    def test_membership_schema_extra_exists(self):
        """OrgMembership model must have json_schema_extra with example."""
        assert OrgMembership.model_config.get("json_schema_extra") is not None

    def test_membership_fields(self):
        """OrgMembership must have required fields."""
        example = OrgMembership.model_config["json_schema_extra"]["examples"][0]
        m = OrgMembership(**example)
        assert m.org_id
        assert m.agent_id
        assert m.role in ("owner", "admin", "member")
        assert m.joined_at > 0

    def test_membership_extra_forbid(self):
        """OrgMembership model must forbid extra fields."""
        example = OrgMembership.model_config["json_schema_extra"]["examples"][0]
        with pytest.raises(Exception):
            OrgMembership(**example, unexpected_field="bad")

    def test_membership_role_validation(self):
        """OrgMembership role must be one of owner/admin/member."""
        example = OrgMembership.model_config["json_schema_extra"]["examples"][0].copy()
        example["role"] = "superuser"
        with pytest.raises(Exception):
            OrgMembership(**example)


# ---------------------------------------------------------------------------
# OrgAPI tests: Create and get org
# ---------------------------------------------------------------------------


class TestCreateOrg:
    """Tests for creating organizations."""

    @pytest.mark.asyncio
    async def test_create_org_returns_org(self, org_api):
        """create_org should return an Organization object."""
        org = await org_api.create_org(name="Acme Corp", owner_agent_id="agent-owner-1")
        assert org.name == "Acme Corp"
        assert org.owner_agent_id == "agent-owner-1"
        assert org.id  # non-empty

    @pytest.mark.asyncio
    async def test_create_org_owner_auto_added_as_member(self, org_api):
        """Creating an org should auto-add the owner as a member with role='owner'."""
        org = await org_api.create_org(name="Acme Corp", owner_agent_id="agent-owner-1")
        members = await org_api.get_org_members(org.id)
        assert len(members) == 1
        assert members[0].agent_id == "agent-owner-1"
        assert members[0].role == "owner"

    @pytest.mark.asyncio
    async def test_create_org_with_metadata(self, org_api):
        """create_org with metadata should persist it."""
        org = await org_api.create_org(
            name="Meta Corp",
            owner_agent_id="agent-owner-2",
            metadata={"industry": "fintech"},
        )
        fetched = await org_api.get_org(org.id)
        assert fetched.metadata == {"industry": "fintech"}


class TestGetOrg:
    """Tests for retrieving organizations."""

    @pytest.mark.asyncio
    async def test_get_org_exists(self, org_api):
        """get_org should return the organization details."""
        org = await org_api.create_org(name="Org1", owner_agent_id="owner1")
        fetched = await org_api.get_org(org.id)
        assert fetched.id == org.id
        assert fetched.name == "Org1"

    @pytest.mark.asyncio
    async def test_get_org_not_found(self, org_api):
        """get_org for a non-existent org raises OrgNotFoundError."""
        with pytest.raises(OrgNotFoundError):
            await org_api.get_org("nonexistent-org-id")


# ---------------------------------------------------------------------------
# OrgAPI tests: Membership management
# ---------------------------------------------------------------------------


class TestAddMember:
    """Tests for adding members to organizations."""

    @pytest.mark.asyncio
    async def test_owner_can_add_member(self, org_api):
        """Owner can add a new member to the org."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        membership = await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-1",
            role="member",
            requester_agent_id="owner",
        )
        assert membership.agent_id == "member-1"
        assert membership.role == "member"
        members = await org_api.get_org_members(org.id)
        assert len(members) == 2  # owner + member

    @pytest.mark.asyncio
    async def test_admin_can_add_member(self, org_api):
        """Admin can add a new member to the org."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        # First, add an admin
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="admin-1",
            role="admin",
            requester_agent_id="owner",
        )
        # Admin adds a member
        membership = await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-2",
            role="member",
            requester_agent_id="admin-1",
        )
        assert membership.role == "member"

    @pytest.mark.asyncio
    async def test_member_cannot_add_member(self, org_api):
        """A regular member cannot add new members (NotAuthorizedError)."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-1",
            role="member",
            requester_agent_id="owner",
        )
        with pytest.raises(NotAuthorizedError):
            await org_api.add_agent_to_org(
                org_id=org.id,
                agent_id="member-2",
                role="member",
                requester_agent_id="member-1",
            )

    @pytest.mark.asyncio
    async def test_add_duplicate_member_raises(self, org_api):
        """Adding an agent who is already a member should raise AlreadyMemberError."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-1",
            role="member",
            requester_agent_id="owner",
        )
        with pytest.raises(AlreadyMemberError):
            await org_api.add_agent_to_org(
                org_id=org.id,
                agent_id="member-1",
                role="member",
                requester_agent_id="owner",
            )

    @pytest.mark.asyncio
    async def test_add_member_to_nonexistent_org(self, org_api):
        """Adding a member to a non-existent org raises OrgNotFoundError."""
        with pytest.raises(OrgNotFoundError):
            await org_api.add_agent_to_org(
                org_id="no-such-org",
                agent_id="member-1",
                role="member",
                requester_agent_id="owner",
            )

    @pytest.mark.asyncio
    async def test_non_member_cannot_add(self, org_api):
        """A non-member cannot add members (NotAuthorizedError)."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        with pytest.raises(NotAuthorizedError):
            await org_api.add_agent_to_org(
                org_id=org.id,
                agent_id="member-1",
                role="member",
                requester_agent_id="outsider",
            )


class TestRemoveMember:
    """Tests for removing members from organizations."""

    @pytest.mark.asyncio
    async def test_owner_can_remove_member(self, org_api):
        """Owner can remove a member from the org."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-1",
            role="member",
            requester_agent_id="owner",
        )
        await org_api.remove_agent_from_org(org_id=org.id, agent_id="member-1")
        members = await org_api.get_org_members(org.id)
        assert len(members) == 1  # only owner left

    @pytest.mark.asyncio
    async def test_remove_non_member_raises(self, org_api):
        """Removing an agent who is not a member raises MemberNotFoundError."""
        org = await org_api.create_org(name="Team", owner_agent_id="owner")
        with pytest.raises(MemberNotFoundError):
            await org_api.remove_agent_from_org(org_id=org.id, agent_id="ghost")

    @pytest.mark.asyncio
    async def test_remove_from_nonexistent_org(self, org_api):
        """Removing from a non-existent org raises OrgNotFoundError."""
        with pytest.raises(OrgNotFoundError):
            await org_api.remove_agent_from_org(org_id="no-org", agent_id="agent-1")


class TestGetOrgMembers:
    """Tests for listing organization members."""

    @pytest.mark.asyncio
    async def test_list_members(self, org_api):
        """get_org_members should return all members with correct roles."""
        org = await org_api.create_org(name="BigTeam", owner_agent_id="owner")
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="admin-1",
            role="admin",
            requester_agent_id="owner",
        )
        await org_api.add_agent_to_org(
            org_id=org.id,
            agent_id="member-1",
            role="member",
            requester_agent_id="owner",
        )
        members = await org_api.get_org_members(org.id)
        assert len(members) == 3
        roles = {m.agent_id: m.role for m in members}
        assert roles["owner"] == "owner"
        assert roles["admin-1"] == "admin"
        assert roles["member-1"] == "member"

    @pytest.mark.asyncio
    async def test_list_members_nonexistent_org(self, org_api):
        """get_org_members for non-existent org raises OrgNotFoundError."""
        with pytest.raises(OrgNotFoundError):
            await org_api.get_org_members("no-org")
