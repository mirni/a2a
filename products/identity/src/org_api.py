"""High-level API for organization management.

Provides CRUD for organizations and membership management with role-based access.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Literal

from .models import Organization, OrgMembership
from .storage import IdentityStorage


class OrgNotFoundError(Exception):
    """Raised when an organization is not found."""

    pass


class MemberNotFoundError(Exception):
    """Raised when a membership record is not found."""

    pass


class NotAuthorizedError(Exception):
    """Raised when the requester does not have permission for the operation."""

    pass


class AlreadyMemberError(Exception):
    """Raised when trying to add an agent who is already a member."""

    pass


class LastOwnerError(Exception):
    """Raised when trying to remove the last owner from an org."""

    pass


@dataclass
class OrgAPI:
    """High-level API for organization operations.

    Attributes:
        storage: IdentityStorage for data access.
    """

    storage: IdentityStorage

    async def create_org(
        self,
        name: str,
        owner_agent_id: str,
        metadata: dict | None = None,
    ) -> Organization:
        """Create a new organization and auto-add the owner as a member.

        Args:
            name: Organization display name.
            owner_agent_id: Agent ID of the organization owner.
            metadata: Optional metadata dict.

        Returns:
            The created Organization object.
        """
        org_id = f"org-{uuid.uuid4().hex[:12]}"
        now = time.time()

        org = Organization(
            id=org_id,
            name=name,
            owner_agent_id=owner_agent_id,
            created_at=now,
            metadata=metadata or {},
        )
        await self.storage.store_organization(org)

        # Auto-add the owner as a member with role='owner'
        owner_membership = OrgMembership(
            org_id=org_id,
            agent_id=owner_agent_id,
            role="owner",
            joined_at=now,
        )
        await self.storage.store_org_membership(owner_membership)

        return org

    async def get_org(self, org_id: str) -> Organization:
        """Get organization details.

        Args:
            org_id: Organization ID.

        Returns:
            Organization object.

        Raises:
            OrgNotFoundError: If the organization does not exist.
        """
        org = await self.storage.get_organization(org_id)
        if org is None:
            raise OrgNotFoundError(f"Organization not found: {org_id}")
        return org

    async def add_agent_to_org(
        self,
        org_id: str,
        agent_id: str,
        role: Literal["owner", "admin", "member"],
        requester_agent_id: str,
    ) -> OrgMembership:
        """Add an agent to an organization.

        Only owners and admins can add members.

        Args:
            org_id: Organization ID.
            agent_id: Agent ID to add.
            role: Role for the new member ('admin' or 'member').
            requester_agent_id: Agent ID of the requester (must be owner/admin).

        Returns:
            The created OrgMembership object.

        Raises:
            OrgNotFoundError: If the organization does not exist.
            NotAuthorizedError: If the requester is not an owner or admin.
            AlreadyMemberError: If the agent is already a member.
        """
        # Verify org exists
        org = await self.storage.get_organization(org_id)
        if org is None:
            raise OrgNotFoundError(f"Organization not found: {org_id}")

        # Verify requester is owner or admin
        requester_membership = await self.storage.get_org_membership(org_id, requester_agent_id)
        if requester_membership is None or requester_membership.role not in ("owner", "admin"):
            raise NotAuthorizedError(f"Agent {requester_agent_id} is not authorized to add members to {org_id}")

        # Check if already a member
        existing = await self.storage.get_org_membership(org_id, agent_id)
        if existing is not None:
            raise AlreadyMemberError(f"Agent {agent_id} is already a member of {org_id}")

        membership = OrgMembership(
            org_id=org_id,
            agent_id=agent_id,
            role=role,
            joined_at=time.time(),
        )
        await self.storage.store_org_membership(membership)
        return membership

    async def remove_agent_from_org(self, org_id: str, agent_id: str) -> None:
        """Remove an agent from an organization.

        Args:
            org_id: Organization ID.
            agent_id: Agent ID to remove.

        Raises:
            OrgNotFoundError: If the organization does not exist.
            MemberNotFoundError: If the agent is not a member.
            LastOwnerError: If the agent is the last owner.
        """
        org = await self.storage.get_organization(org_id)
        if org is None:
            raise OrgNotFoundError(f"Organization not found: {org_id}")

        # Check if target is an owner and the last one
        membership = await self.storage.get_org_membership(org_id, agent_id)
        if membership is not None and membership.role == "owner":
            all_members = await self.storage.list_org_memberships(org_id)
            owner_count = sum(1 for m in all_members if m.role == "owner")
            if owner_count <= 1:
                raise LastOwnerError(
                    f"Cannot remove agent {agent_id}: they are the last owner of {org_id}"
                )

        deleted = await self.storage.delete_org_membership(org_id, agent_id)
        if not deleted:
            raise MemberNotFoundError(f"Agent {agent_id} is not a member of {org_id}")

    async def get_org_members(self, org_id: str) -> list[OrgMembership]:
        """List all members of an organization.

        Args:
            org_id: Organization ID.

        Returns:
            List of OrgMembership objects.

        Raises:
            OrgNotFoundError: If the organization does not exist.
        """
        org = await self.storage.get_organization(org_id)
        if org is None:
            raise OrgNotFoundError(f"Organization not found: {org_id}")

        return await self.storage.list_org_memberships(org_id)
