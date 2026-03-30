"""TDD tests for organization billing: org wallets, member spending, limits.

Covers:
- Create org wallet
- Deposit to org wallet
- Get org wallet balance
- Member charge against org wallet (owner/admin unlimited)
- Member spending limit enforcement
- Spending report per-member
- Negative: non-member cannot access org wallet
- Negative: member exceeding spend limit gets rejected
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from src.org_billing import (
    NotOrgMemberError,
    OrgBilling,
    OrgSpendLimitExceededError,
    OrgWalletNotFoundError,
)
from src.storage import StorageBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def billing_storage(tmp_path):
    """Provide a connected StorageBackend for org billing tests."""
    dsn = f"sqlite:///{tmp_path}/org_billing_test.db"
    backend = StorageBackend(dsn=dsn)
    await backend.connect(apply_migrations=True)
    yield backend
    await backend.close()


@pytest_asyncio.fixture
async def org_billing(billing_storage):
    """Provide an OrgBilling instance with pre-seeded org membership data."""
    return OrgBilling(storage=billing_storage)


# ---------------------------------------------------------------------------
# Org wallet creation
# ---------------------------------------------------------------------------


class TestOrgWalletCreate:
    """Tests for creating organization wallets."""

    @pytest.mark.asyncio
    async def test_create_org_wallet(self, org_billing):
        """create_org_wallet should create a wallet with zero balance."""
        wallet = await org_billing.create_org_wallet(org_id="org-1")
        assert wallet["org_id"] == "org-1"
        assert wallet["balance"] == Decimal("0")

    @pytest.mark.asyncio
    async def test_create_org_wallet_with_initial_balance(self, org_billing):
        """create_org_wallet with initial_balance should set the balance."""
        wallet = await org_billing.create_org_wallet(org_id="org-2", initial_balance=Decimal("1000.00"))
        assert wallet["balance"] == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_create_duplicate_org_wallet_raises(self, org_billing):
        """Creating a wallet for the same org twice should raise ValueError."""
        await org_billing.create_org_wallet(org_id="org-dup")
        with pytest.raises(ValueError, match="already exists"):
            await org_billing.create_org_wallet(org_id="org-dup")


# ---------------------------------------------------------------------------
# Org wallet deposit
# ---------------------------------------------------------------------------


class TestOrgDeposit:
    """Tests for depositing into org wallets."""

    @pytest.mark.asyncio
    async def test_deposit_increases_balance(self, org_billing):
        """deposit_org should increase the org wallet balance."""
        await org_billing.create_org_wallet(org_id="org-1")
        new_balance = await org_billing.deposit_org(org_id="org-1", amount=Decimal("500.00"))
        assert new_balance == Decimal("500.00")

    @pytest.mark.asyncio
    async def test_deposit_zero_raises(self, org_billing):
        """Depositing zero should raise ValueError."""
        await org_billing.create_org_wallet(org_id="org-1")
        with pytest.raises(ValueError, match="positive"):
            await org_billing.deposit_org(org_id="org-1", amount=Decimal("0"))

    @pytest.mark.asyncio
    async def test_deposit_negative_raises(self, org_billing):
        """Depositing negative should raise ValueError."""
        await org_billing.create_org_wallet(org_id="org-1")
        with pytest.raises(ValueError, match="positive"):
            await org_billing.deposit_org(org_id="org-1", amount=Decimal("-10"))

    @pytest.mark.asyncio
    async def test_deposit_to_nonexistent_wallet(self, org_billing):
        """Depositing to a non-existent org wallet raises OrgWalletNotFoundError."""
        with pytest.raises(OrgWalletNotFoundError):
            await org_billing.deposit_org(org_id="no-wallet", amount=Decimal("100"))


# ---------------------------------------------------------------------------
# Org wallet balance
# ---------------------------------------------------------------------------


class TestGetOrgWallet:
    """Tests for getting org wallet info."""

    @pytest.mark.asyncio
    async def test_get_org_wallet(self, org_billing):
        """get_org_wallet should return the wallet with current balance."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("250.00"))
        wallet = await org_billing.get_org_wallet(org_id="org-1")
        assert wallet["org_id"] == "org-1"
        assert wallet["balance"] == Decimal("250.00")

    @pytest.mark.asyncio
    async def test_get_org_wallet_not_found(self, org_billing):
        """get_org_wallet for a non-existent org raises OrgWalletNotFoundError."""
        with pytest.raises(OrgWalletNotFoundError):
            await org_billing.get_org_wallet(org_id="ghost-org")


# ---------------------------------------------------------------------------
# Member charging against org wallet
# ---------------------------------------------------------------------------


class TestMemberCharge:
    """Tests for members charging against org wallet based on role."""

    @pytest.mark.asyncio
    async def test_owner_can_charge_unlimited(self, org_billing):
        """Owner can charge any amount against the org wallet."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        # Register membership: owner
        await org_billing.register_member(org_id="org-1", agent_id="owner-1", role="owner")
        new_balance = await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="owner-1",
            amount=Decimal("800"),
            description="big purchase",
        )
        assert new_balance == Decimal("200")

    @pytest.mark.asyncio
    async def test_admin_can_charge_unlimited(self, org_billing):
        """Admin can charge any amount against the org wallet."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        await org_billing.register_member(org_id="org-1", agent_id="admin-1", role="admin")
        new_balance = await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="admin-1",
            amount=Decimal("999"),
            description="admin spend",
        )
        assert new_balance == Decimal("1")

    @pytest.mark.asyncio
    async def test_member_within_spend_limit(self, org_billing):
        """Member can charge if within their spend limit."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        await org_billing.register_member(
            org_id="org-1",
            agent_id="member-1",
            role="member",
            spend_limit=Decimal("200"),
        )
        new_balance = await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="member-1",
            amount=Decimal("150"),
            description="api call",
        )
        assert new_balance == Decimal("850")

    @pytest.mark.asyncio
    async def test_member_exceeding_spend_limit_rejected(self, org_billing):
        """Member exceeding spend limit gets OrgSpendLimitExceededError."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        await org_billing.register_member(
            org_id="org-1",
            agent_id="member-1",
            role="member",
            spend_limit=Decimal("100"),
        )
        # First charge within limit
        await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="member-1",
            amount=Decimal("80"),
            description="first charge",
        )
        # Second charge would exceed limit (80 + 50 > 100)
        with pytest.raises(OrgSpendLimitExceededError):
            await org_billing.charge_to_org(
                org_id="org-1",
                agent_id="member-1",
                amount=Decimal("50"),
                description="over limit",
            )

    @pytest.mark.asyncio
    async def test_non_member_cannot_charge(self, org_billing):
        """Non-member cannot charge against the org wallet."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        with pytest.raises(NotOrgMemberError):
            await org_billing.charge_to_org(
                org_id="org-1",
                agent_id="outsider",
                amount=Decimal("10"),
                description="sneaky",
            )

    @pytest.mark.asyncio
    async def test_charge_exceeding_wallet_balance_raises(self, org_billing):
        """Charging more than the wallet balance should raise InsufficientCredits-like error."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("50"))
        await org_billing.register_member(org_id="org-1", agent_id="owner-1", role="owner")
        with pytest.raises(Exception):  # InsufficientCreditsError or similar
            await org_billing.charge_to_org(
                org_id="org-1",
                agent_id="owner-1",
                amount=Decimal("100"),
                description="too much",
            )


# ---------------------------------------------------------------------------
# Spending reports
# ---------------------------------------------------------------------------


class TestOrgSpending:
    """Tests for org spending reports."""

    @pytest.mark.asyncio
    async def test_get_org_spending_all_members(self, org_billing):
        """get_org_spending without agent_id returns all member spending."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        await org_billing.register_member(org_id="org-1", agent_id="owner-1", role="owner")
        await org_billing.register_member(
            org_id="org-1",
            agent_id="member-1",
            role="member",
            spend_limit=Decimal("500"),
        )
        await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="owner-1",
            amount=Decimal("100"),
            description="owner charge",
        )
        await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="member-1",
            amount=Decimal("50"),
            description="member charge",
        )
        report = await org_billing.get_org_spending(org_id="org-1")
        assert len(report) == 2
        spending_by_agent = {r["agent_id"]: r["total_spent"] for r in report}
        assert spending_by_agent["owner-1"] == Decimal("100")
        assert spending_by_agent["member-1"] == Decimal("50")

    @pytest.mark.asyncio
    async def test_get_org_spending_single_member(self, org_billing):
        """get_org_spending with agent_id returns just that member's spending."""
        await org_billing.create_org_wallet(org_id="org-1")
        await org_billing.deposit_org(org_id="org-1", amount=Decimal("1000"))
        await org_billing.register_member(org_id="org-1", agent_id="owner-1", role="owner")
        await org_billing.charge_to_org(
            org_id="org-1",
            agent_id="owner-1",
            amount=Decimal("75"),
            description="owner charge",
        )
        report = await org_billing.get_org_spending(org_id="org-1", agent_id="owner-1")
        assert len(report) == 1
        assert report[0]["agent_id"] == "owner-1"
        assert report[0]["total_spent"] == Decimal("75")

    @pytest.mark.asyncio
    async def test_get_org_spending_empty(self, org_billing):
        """get_org_spending with no charges returns empty or zero totals."""
        await org_billing.create_org_wallet(org_id="org-1")
        report = await org_billing.get_org_spending(org_id="org-1")
        assert report == []

    @pytest.mark.asyncio
    async def test_get_org_spending_nonexistent_wallet(self, org_billing):
        """get_org_spending for non-existent org raises OrgWalletNotFoundError."""
        with pytest.raises(OrgWalletNotFoundError):
            await org_billing.get_org_spending(org_id="ghost-org")
