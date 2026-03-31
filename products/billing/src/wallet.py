"""Agent wallet operations: credit-based accounts with deposit/withdraw/balance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared_src.pricing_config import load_pricing_config

from .storage import StorageBackend

_pricing = load_pricing_config()


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


class WalletFrozenError(Exception):
    """Raised when operating on a frozen wallet."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        super().__init__(f"Wallet is frozen for agent {agent_id}")


@dataclass
class Wallet:
    """High-level wallet operations wrapping the storage backend."""

    storage: StorageBackend

    async def create(
        self,
        agent_id: str,
        initial_balance: float = 0.0,
        signup_bonus: bool = True,
    ) -> dict[str, Any]:
        """Create a new wallet for an agent. Returns wallet dict.

        Args:
            agent_id: Unique agent identifier.
            initial_balance: Optional extra credits on top of signup bonus.
            signup_bonus: If True (default), grant signup bonus from pricing.json.
        """
        existing = await self.storage.get_wallet(agent_id)
        if existing is not None:
            raise ValueError(f"Wallet already exists for agent {agent_id}")

        bonus = float(_pricing.credits["signup_bonus"]) if signup_bonus else 0.0
        total_initial = initial_balance + bonus

        wallet = await self.storage.create_wallet(agent_id, total_initial)

        if bonus > 0:
            await self.storage.record_transaction(agent_id, bonus, "signup_bonus", "Signup bonus credits")
            await self.storage.emit_event("wallet.signup_bonus", agent_id, {"amount": bonus})

        if initial_balance > 0:
            await self.storage.record_transaction(agent_id, initial_balance, "deposit", "Initial deposit")

        await self.storage.emit_event("wallet.created", agent_id, {"balance": total_initial})
        return wallet

    async def get_balance(self, agent_id: str, currency: str = "CREDITS") -> float:
        """Return current balance for an agent in a specific currency.

        Raises WalletNotFoundError if the agent has no wallet at all (for CREDITS).
        For non-CREDITS currencies, returns 0.0 if no balance exists.
        """
        if currency == "CREDITS":
            wallet = await self.storage.get_wallet(agent_id)
            if wallet is None:
                raise WalletNotFoundError(agent_id)
            return wallet["balance"]
        # For non-CREDITS currencies, first verify the agent has a wallet
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        return await self.storage.get_currency_balance(agent_id, currency)

    async def deposit(self, agent_id: str, amount: float, description: str = "", currency: str = "CREDITS") -> float:
        """Add funds to an agent's wallet in a specific currency. Returns new balance."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        if await self.storage.is_wallet_frozen(agent_id):
            raise WalletFrozenError(agent_id)
        success, new_balance = await self.storage.atomic_currency_credit(agent_id, amount, currency)
        if not success:
            raise WalletNotFoundError(agent_id)
        await self.storage.record_transaction(agent_id, amount, "deposit", description, currency=currency)
        await self.storage.emit_event(
            "wallet.deposit",
            agent_id,
            {"amount": amount, "new_balance": new_balance, "currency": currency},
        )
        return new_balance

    async def withdraw(self, agent_id: str, amount: float, description: str = "", currency: str = "CREDITS") -> float:
        """Remove funds from an agent's wallet in a specific currency. Returns new balance.

        Raises InsufficientCreditsError if balance is too low.
        Uses atomic UPDATE WHERE balance >= ? to prevent race conditions.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if await self.storage.is_wallet_frozen(agent_id):
            raise WalletFrozenError(agent_id)
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        success, new_balance = await self.storage.atomic_currency_debit_strict(agent_id, amount, currency)
        if not success:
            available = await self.storage.get_currency_balance(agent_id, currency)
            raise InsufficientCreditsError(agent_id, amount, available)
        await self.storage.record_transaction(agent_id, -amount, "withdrawal", description, currency=currency)
        await self.storage.emit_event(
            "wallet.withdrawal",
            agent_id,
            {"amount": amount, "new_balance": new_balance, "currency": currency},
        )
        if currency == "CREDITS":
            new_balance = await self._maybe_auto_reload(agent_id, new_balance)
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
        new_balance = await self._maybe_auto_reload(agent_id, new_balance)
        return new_balance

    async def get_transactions(self, agent_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Return transaction history for an agent."""
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)
        return await self.storage.get_transactions(agent_id, limit, offset)

    # -----------------------------------------------------------------------
    # Multi-currency conversion
    # -----------------------------------------------------------------------

    async def convert_currency(
        self,
        agent_id: str,
        amount: float,
        from_currency: str,
        to_currency: str,
        exchange_service: Any,
    ) -> dict[str, Any]:
        """Convert funds between currency balances for an agent.

        Atomically withdraws ``amount`` from ``from_currency`` balance and
        deposits the converted amount into ``to_currency`` balance using the
        exchange service.  Both operations are wrapped in a single SQLite
        transaction so that if either step fails, the entire operation is
        rolled back and no funds are lost.

        Args:
            agent_id: The agent whose balances to modify.
            amount: Amount to convert in the source currency.
            from_currency: Source currency code (e.g. "USD").
            to_currency: Target currency code (e.g. "CREDITS").
            exchange_service: An ExchangeRateService instance.

        Returns:
            Dict with from_amount, to_amount, from_currency, to_currency.
        """
        import time as _time
        from decimal import Decimal as _Decimal

        from .models import Currency

        if amount <= 0:
            raise ValueError("Conversion amount must be positive")

        # --- Pre-transaction checks (read-only) ---
        if await self.storage.is_wallet_frozen(agent_id):
            raise WalletFrozenError(agent_id)
        wallet = await self.storage.get_wallet(agent_id)
        if wallet is None:
            raise WalletNotFoundError(agent_id)

        # Look up exchange rate *before* starting the transaction so the
        # rate lookup (which may hit the DB) doesn't conflict with our
        # explicit transaction.
        from_cur = Currency(from_currency)
        to_cur = Currency(to_currency)
        converted = await exchange_service.convert(_Decimal(str(amount)), from_cur, to_cur)
        to_amount = float(converted.amount)

        # --- Atomic transaction: withdraw + deposit ---
        db = self.storage.db
        description = f"convert:{from_currency}->{to_currency}"
        amt_debit = self.storage._to_atomic(amount)
        amt_credit = self.storage._to_atomic(to_amount)
        now = _time.time()

        await db.execute("BEGIN IMMEDIATE")
        try:
            # Debit source currency
            debit_ok = await self.storage._debit_in_txn(
                db, agent_id, amt_debit, from_currency, now,
            )
            if not debit_ok:
                available = await self.storage.get_currency_balance(agent_id, from_currency)
                raise InsufficientCreditsError(agent_id, amount, available)

            # Credit target currency
            await self.storage._credit_in_txn(
                db, agent_id, amt_credit, to_currency, now,
            )

            # Record transactions inside the same DB transaction
            await db.execute(
                "INSERT INTO transactions (agent_id, amount, tx_type, description, currency, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, -int(_Decimal(str(amount)) * self.storage._scale()), "withdrawal", description, from_currency, now),
            )
            await db.execute(
                "INSERT INTO transactions (agent_id, amount, tx_type, description, currency, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (agent_id, int(_Decimal(str(to_amount)) * self.storage._scale()), "deposit", description, to_currency, now),
            )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        # --- Post-transaction side effects (events) ---
        await self.storage.emit_event(
            "wallet.withdrawal",
            agent_id,
            {"amount": amount, "currency": from_currency, "description": description},
        )
        await self.storage.emit_event(
            "wallet.deposit",
            agent_id,
            {"amount": to_amount, "currency": to_currency, "description": description},
        )

        return {
            "from_amount": amount,
            "to_amount": to_amount,
            "from_currency": from_currency,
            "to_currency": to_currency,
        }

    # -----------------------------------------------------------------------
    # Auto-reload
    # -----------------------------------------------------------------------

    async def enable_auto_reload(self, agent_id: str, threshold: float, reload_amount: float) -> None:
        """Enable auto-reload: when balance drops below threshold, add reload_amount."""
        await self.storage.set_auto_reload(agent_id, threshold, reload_amount, enabled=True)

    async def disable_auto_reload(self, agent_id: str) -> None:
        """Disable auto-reload for an agent."""
        config = await self.storage.get_auto_reload(agent_id)
        if config is not None:
            await self.storage.set_auto_reload(agent_id, config["threshold"], config["reload_amount"], enabled=False)

    async def get_auto_reload_config(self, agent_id: str) -> dict[str, Any] | None:
        """Return auto-reload config for an agent, or None if not configured."""
        return await self.storage.get_auto_reload(agent_id)

    async def _maybe_auto_reload(self, agent_id: str, current_balance: float) -> float:
        """Check if auto-reload should trigger, and if so, add credits."""
        config = await self.storage.get_auto_reload(agent_id)
        if config is None or not config["enabled"]:
            return current_balance
        if current_balance >= config["threshold"]:
            return current_balance

        reload_amount = config["reload_amount"]
        success, new_balance = await self.storage.atomic_credit(agent_id, reload_amount)
        if success:
            await self.storage.record_transaction(agent_id, reload_amount, "auto_reload", "Auto-reload triggered")
            await self.storage.emit_event(
                "wallet.auto_reload",
                agent_id,
                {"amount": reload_amount, "new_balance": new_balance, "trigger_balance": current_balance},
            )
            return new_balance
        return current_balance
