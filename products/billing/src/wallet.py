"""Agent wallet operations: credit-based accounts with deposit/withdraw/balance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .storage import StorageBackend


class InsufficientCreditsError(Exception):
    """Raised when a withdrawal would exceed available balance."""

    def __init__(self, agent_id: str, requested: float, available: float) -> None:
        self.agent_id = agent_id
        self.requested = requested
        self.available = available
        super().__init__(f"Agent {agent_id}: insufficient credits. Requested {requested}, available {available}")


class WalletNotFoundError(Exception):
    """Raised when operating on a non-existent wallet."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"Wallet not found for agent {agent_id}")


@dataclass
class Wallet:
    """High-level wallet operations wrapping the storage backend."""

    storage: StorageBackend

    async def create(self, agent_id: str, initial_balance: float = 0.0) -> dict[str, Any]:
        """Create a new wallet for an agent. Returns wallet dict."""
        existing = await self.storage.get_wallet(agent_id)
        if existing is not None:
            raise ValueError(f"Wallet already exists for agent {agent_id}")
        wallet = await self.storage.create_wallet(agent_id, initial_balance)
        if initial_balance > 0:
            await self.storage.record_transaction(agent_id, initial_balance, "deposit", "Initial deposit")
            await self.storage.emit_event(
                "wallet.created",
                agent_id,
                {"balance": initial_balance},
            )
        else:
            await self.storage.emit_event(
                "wallet.created",
                agent_id,
                {"balance": 0.0},
            )
        return wallet

    async def get_balance(self, agent_id: str) -> float:
        """Return current balance for an agent. Raises WalletNotFoundError if missing."""
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        return wallet["balance"]

    async def deposit(self, agent_id: str, amount: float, description: str = "") -> float:
        """Add credits to an agent's wallet. Returns new balance."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        success, new_balance = await self.storage.atomic_credit(agent_id, amount)
        if not success:
            raise WalletNotFoundError(agent_id)
        await self.storage.record_transaction(agent_id, amount, "deposit", description)
        await self.storage.emit_event(
            "wallet.deposit",
            agent_id,
            {"amount": amount, "new_balance": new_balance},
        )
        return new_balance

    async def withdraw(self, agent_id: str, amount: float, description: str = "") -> float:
        """Remove credits from an agent's wallet. Returns new balance.

        Raises InsufficientCreditsError if balance is too low.
        Uses atomic UPDATE WHERE balance >= ? to prevent race conditions.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        success, new_balance = await self.storage.atomic_debit_strict(agent_id, amount)
        if not success:
            # Re-fetch current balance for the error message
            current = await self.storage.get_wallet(agent_id)
            available = current["balance"] if current else 0.0
            raise InsufficientCreditsError(agent_id, amount, available)
        await self.storage.record_transaction(agent_id, -amount, "withdrawal", description)
        await self.storage.emit_event(
            "wallet.withdrawal",
            agent_id,
            {"amount": amount, "new_balance": new_balance},
        )
        return new_balance

    async def charge(self, agent_id: str, amount: float, description: str = "") -> float:
        """Deduct credits for usage (metered call). Returns new balance.

        Raises InsufficientCreditsError if balance is too low.
        Uses atomic UPDATE WHERE balance >= ? to prevent race conditions.
        """
        if amount <= 0:
            raise ValueError("Charge amount must be positive")
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        success, new_balance = await self.storage.atomic_debit_strict(agent_id, amount)
        if not success:
            current = await self.storage.get_wallet(agent_id)
            available = current["balance"] if current else 0.0
            raise InsufficientCreditsError(agent_id, amount, available)
        await self.storage.record_transaction(agent_id, -amount, "charge", description)
        return new_balance

    async def get_transactions(self, agent_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Return transaction history for an agent."""
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        return await self.storage.get_transactions(agent_id, limit, offset)
