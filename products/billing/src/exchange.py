"""Exchange rate service for multi-currency support.

Stores exchange rates in the billing database and provides
conversion between any two supported currencies.

Default rates (approximate, for initialization):
  1 USD  = 100 CREDITS
  1 EUR  = 110 CREDITS
  1 GBP  = 125 CREDITS
  1 BTC  = 6,000,000 CREDITS
  1 ETH  = 400,000 CREDITS
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from .models import Currency, CurrencyAmount
from .storage import StorageBackend


class UnsupportedCurrencyError(Exception):
    """Raised when no exchange rate exists for a requested currency pair."""

    def __init__(self, from_currency: Currency, to_currency: Currency) -> None:
        self.from_currency = from_currency
        self.to_currency = to_currency
        super().__init__(f"No exchange rate found for {from_currency.value} -> {to_currency.value}")


# Default rates: all expressed as X -> CREDITS
_DEFAULT_RATES: dict[tuple[str, str], Decimal] = {
    ("USD", "CREDITS"): Decimal("100"),
    ("EUR", "CREDITS"): Decimal("110"),
    ("GBP", "CREDITS"): Decimal("125"),
    ("BTC", "CREDITS"): Decimal("6000000"),
    ("ETH", "CREDITS"): Decimal("400000"),
}


@dataclass
class ExchangeRateService:
    """Service for looking up and converting between currencies.

    Rates are stored in the ``exchange_rates`` table and looked up at
    query time. ``initialize_default_rates`` populates the table with
    seed values for all default pairs (and their inverses).
    """

    storage: StorageBackend

    async def _ensure_table(self) -> None:
        """Create the exchange_rates table if it does not exist."""
        await self.storage.db.execute(
            """CREATE TABLE IF NOT EXISTS exchange_rates (
                from_currency TEXT NOT NULL,
                to_currency   TEXT NOT NULL,
                rate          TEXT NOT NULL,
                updated_at    REAL NOT NULL,
                PRIMARY KEY (from_currency, to_currency)
            )"""
        )
        await self.storage.db.commit()

    async def initialize_default_rates(self) -> None:
        """Populate the exchange_rates table with default seed rates.

        Inserts both directions for each pair (e.g. USD->CREDITS and CREDITS->USD).
        Uses INSERT OR IGNORE so existing rates are not overwritten.
        """
        await self._ensure_table()
        now = time.time()
        for (from_c, to_c), rate in _DEFAULT_RATES.items():
            inverse = Decimal("1") / rate
            await self.storage.db.execute(
                "INSERT OR IGNORE INTO exchange_rates (from_currency, to_currency, rate, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (from_c, to_c, str(rate), now),
            )
            await self.storage.db.execute(
                "INSERT OR IGNORE INTO exchange_rates (from_currency, to_currency, rate, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (to_c, from_c, str(inverse), now),
            )
        await self.storage.db.commit()

    async def get_rate(self, from_currency: Currency, to_currency: Currency) -> Decimal:
        """Look up the exchange rate from one currency to another.

        Returns ``Decimal("1")`` for identity conversion (same currency).

        First tries a direct lookup in the ``exchange_rates`` table. If no
        direct rate exists, falls back to a two-hop lookup via ``CREDITS``
        as the pivot currency — ``from → CREDITS → to`` — so cross-currency
        pairs like ``USD → ETH`` work without requiring a dedicated row.
        This fixes audit finding HIGH-5 (``/v1/billing/wallets/{id}/convert``
        USD→ETH 500).

        Raises ``UnsupportedCurrencyError`` if neither the direct nor the
        two-hop path yields a rate.
        """
        if from_currency == to_currency:
            return Decimal("1")

        await self._ensure_table()

        # 1. Direct lookup.
        cursor = await self.storage.db.execute(
            "SELECT rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ?",
            (from_currency.value, to_currency.value),
        )
        row = await cursor.fetchone()
        if row is not None:
            return Decimal(row[0])

        # 2. Two-hop pivot via CREDITS: from → CREDITS → to.
        if from_currency != Currency.CREDITS and to_currency != Currency.CREDITS:
            cursor_from = await self.storage.db.execute(
                "SELECT rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ?",
                (from_currency.value, Currency.CREDITS.value),
            )
            from_row = await cursor_from.fetchone()
            cursor_to = await self.storage.db.execute(
                "SELECT rate FROM exchange_rates WHERE from_currency = ? AND to_currency = ?",
                (Currency.CREDITS.value, to_currency.value),
            )
            to_row = await cursor_to.fetchone()
            if from_row is not None and to_row is not None:
                return Decimal(from_row[0]) * Decimal(to_row[0])

        raise UnsupportedCurrencyError(from_currency, to_currency)

    async def convert(
        self,
        amount: Decimal,
        from_currency: Currency,
        to_currency: Currency,
    ) -> CurrencyAmount:
        """Convert an amount from one currency to another.

        Returns a CurrencyAmount in the target currency.
        """
        rate = await self.get_rate(from_currency, to_currency)
        converted = amount * rate
        return CurrencyAmount(amount=converted, currency=to_currency)

    async def set_rate(
        self,
        from_currency: Currency,
        to_currency: Currency,
        rate: Decimal,
    ) -> None:
        """Set (or update) the exchange rate for a currency pair.

        Also updates the inverse direction automatically.
        """
        await self._ensure_table()
        now = time.time()
        inverse = Decimal("1") / rate

        await self.storage.db.execute(
            "INSERT INTO exchange_rates (from_currency, to_currency, rate, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(from_currency, to_currency) DO UPDATE SET rate = excluded.rate, updated_at = excluded.updated_at",
            (from_currency.value, to_currency.value, str(rate), now),
        )
        await self.storage.db.execute(
            "INSERT INTO exchange_rates (from_currency, to_currency, rate, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(from_currency, to_currency) DO UPDATE SET rate = excluded.rate, updated_at = excluded.updated_at",
            (to_currency.value, from_currency.value, str(inverse), now),
        )
        await self.storage.db.commit()
