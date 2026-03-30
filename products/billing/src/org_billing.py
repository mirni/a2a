"""Organization billing: shared wallets with role-based spending controls.

Provides org wallet creation, deposits, member charges with spend limits,
and spending reports. All currency values use Decimal for precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .storage import StorageBackend

try:
    from shared_src.money import SCALE
except ImportError:
    from src.money import SCALE


class OrgWalletNotFoundError(Exception):
    """Raised when an org wallet is not found."""

    def __init__(self, org_id: str) -> None:
        self.org_id = org_id
        super().__init__(f"Org wallet not found for org {org_id}")


class OrgSpendLimitExceededError(Exception):
    """Raised when a member's charge would exceed their spend limit."""

    def __init__(self, agent_id: str, requested: Decimal, limit: Decimal, spent: Decimal) -> None:
        self.agent_id = agent_id
        self.requested = requested
        self.limit = limit
        self.spent = spent
        super().__init__(
            f"Agent {agent_id}: spend limit exceeded. Requested {requested}, limit {limit}, already spent {spent}"
        )


class NotOrgMemberError(Exception):
    """Raised when an agent is not a member of the organization."""

    def __init__(self, org_id: str, agent_id: str) -> None:
        self.org_id = org_id
        self.agent_id = agent_id
        super().__init__(f"Agent {agent_id} is not a member of org {org_id}")


class OrgInsufficientCreditsError(Exception):
    """Raised when the org wallet has insufficient balance."""

    def __init__(self, org_id: str, requested: Decimal, available: Decimal) -> None:
        self.org_id = org_id
        self.requested = requested
        self.available = available
        super().__init__(f"Org {org_id}: insufficient credits. Requested {requested}, available {available}")


def _decimal_to_atomic(value: Decimal) -> int:
    """Convert a Decimal credit amount to atomic units."""
    return int(value * SCALE)


def _float_to_decimal(value: float) -> Decimal:
    """Convert a float from storage to Decimal."""
    return Decimal(str(value))


@dataclass
class OrgBilling:
    """High-level API for organization billing operations.

    Manages org wallets, member spending, and spending reports.
    All monetary amounts are Decimal for precision.
    """

    storage: StorageBackend

    # -------------------------------------------------------------------
    # Org wallet lifecycle
    # -------------------------------------------------------------------

    async def create_org_wallet(self, org_id: str, initial_balance: Decimal = Decimal("0")) -> dict[str, Any]:
        """Create an org wallet.

        Args:
            org_id: Organization ID.
            initial_balance: Initial balance as Decimal.

        Returns:
            Dict with org_id, balance (Decimal), created_at, updated_at.

        Raises:
            ValueError: If a wallet already exists for this org.
        """
        existing = await self.storage.get_org_wallet(org_id)
        if existing is not None:
            raise ValueError(f"Org wallet already exists for org {org_id}")

        bal_atomic = _decimal_to_atomic(initial_balance)
        result = await self.storage.create_org_wallet(org_id, bal_atomic)
        result["balance"] = _float_to_decimal(result["balance"])
        return result

    async def get_org_wallet(self, org_id: str) -> dict[str, Any]:
        """Get org wallet details.

        Returns:
            Dict with org_id, balance (Decimal), created_at, updated_at.

        Raises:
            OrgWalletNotFoundError: If no wallet exists for this org.
        """
        result = await self.storage.get_org_wallet(org_id)
        if result is None:
            raise OrgWalletNotFoundError(org_id)
        result["balance"] = _float_to_decimal(result["balance"])
        return result

    async def deposit_org(self, org_id: str, amount: Decimal) -> Decimal:
        """Deposit credits to an org wallet.

        Args:
            org_id: Organization ID.
            amount: Amount to deposit (must be positive).

        Returns:
            New balance as Decimal.

        Raises:
            ValueError: If amount is not positive.
            OrgWalletNotFoundError: If no wallet exists.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")

        amt_atomic = _decimal_to_atomic(amount)
        success, new_balance_float = await self.storage.atomic_org_credit(org_id, amt_atomic)
        if not success:
            raise OrgWalletNotFoundError(org_id)
        return _float_to_decimal(new_balance_float)

    # -------------------------------------------------------------------
    # Member management (billing-side)
    # -------------------------------------------------------------------

    async def register_member(
        self,
        org_id: str,
        agent_id: str,
        role: str,
        spend_limit: Decimal | None = None,
    ) -> None:
        """Register a member for billing purposes.

        Args:
            org_id: Organization ID.
            agent_id: Agent ID.
            role: Role ('owner', 'admin', 'member').
            spend_limit: Optional per-period spend limit (only enforced for 'member' role).
        """
        limit_atomic = _decimal_to_atomic(spend_limit) if spend_limit is not None else None
        await self.storage.register_org_member(org_id, agent_id, role, limit_atomic)

    # -------------------------------------------------------------------
    # Charging against org wallet
    # -------------------------------------------------------------------

    async def charge_to_org(
        self,
        org_id: str,
        agent_id: str,
        amount: Decimal,
        description: str = "",
    ) -> Decimal:
        """Charge credits against the org wallet on behalf of a member.

        Owner/admin: unlimited spending (subject only to wallet balance).
        Member: subject to configurable spend_limit per period.

        Args:
            org_id: Organization ID.
            agent_id: Agent making the charge.
            amount: Amount to charge.
            description: Optional description.

        Returns:
            New org wallet balance as Decimal.

        Raises:
            NotOrgMemberError: If agent is not a member.
            OrgSpendLimitExceededError: If member would exceed spend limit.
            OrgInsufficientCreditsError: If wallet balance is insufficient.
        """
        # Verify membership
        member = await self.storage.get_org_member(org_id, agent_id)
        if member is None:
            raise NotOrgMemberError(org_id, agent_id)

        # Check spend limit for regular members
        if member["role"] == "member" and member.get("spend_limit") is not None:
            limit = _float_to_decimal(member["spend_limit"])
            # Get current spending
            spending_rows = await self.storage.get_org_member_spending(org_id, agent_id)
            current_spent = _float_to_decimal(spending_rows[0]["total_spent"]) if spending_rows else Decimal("0")
            if current_spent + amount > limit:
                raise OrgSpendLimitExceededError(agent_id, amount, limit, current_spent)

        # Debit from org wallet
        amt_atomic = _decimal_to_atomic(amount)
        success, new_balance_float = await self.storage.atomic_org_debit_strict(org_id, amt_atomic)
        if not success:
            # Check if wallet exists but insufficient balance
            wallet = await self.storage.get_org_wallet(org_id)
            if wallet is None:
                raise OrgWalletNotFoundError(org_id)
            available = _float_to_decimal(wallet["balance"])
            raise OrgInsufficientCreditsError(org_id, amount, available)

        # Record the transaction
        await self.storage.record_org_transaction(org_id, agent_id, amt_atomic, "charge", description)

        return _float_to_decimal(new_balance_float)

    # -------------------------------------------------------------------
    # Spending reports
    # -------------------------------------------------------------------

    async def get_org_spending(self, org_id: str, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Get spending report for an organization.

        Args:
            org_id: Organization ID.
            agent_id: Optional agent to filter by.

        Returns:
            List of dicts with agent_id and total_spent (Decimal).

        Raises:
            OrgWalletNotFoundError: If no wallet exists for this org.
        """
        wallet = await self.storage.get_org_wallet(org_id)
        if wallet is None:
            raise OrgWalletNotFoundError(org_id)

        rows = await self.storage.get_org_member_spending(org_id, agent_id)
        # Convert total_spent from float to Decimal
        for row in rows:
            row["total_spent"] = _float_to_decimal(row["total_spent"])
        return rows
