"""Currency models for multi-currency support.

Defines Currency enum, CurrencyAmount, and ExchangeRate models.
All monetary amounts use Decimal for precision (CLAUDE.md requirement).
"""

from __future__ import annotations

import time
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Currency(StrEnum):
    """Supported currencies on the platform."""

    CREDITS = "CREDITS"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    BTC = "BTC"
    ETH = "ETH"
    USDC = "USDC"


class CurrencyAmount(BaseModel):
    """A monetary amount tagged with its currency.

    Uses Decimal for all amounts (never float) to avoid precision loss,
    especially important for BTC (8 decimal places).
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "amount": "49.99",
                    "currency": "USD",
                },
                {
                    "amount": "0.00500000",
                    "currency": "BTC",
                },
                {
                    "amount": "1000",
                    "currency": "CREDITS",
                },
            ]
        },
    )

    amount: Decimal
    currency: Currency

    @field_serializer("amount")
    @classmethod
    def _serialize_amount(cls, v: Decimal) -> str:
        return str(v)


class ExchangeRate(BaseModel):
    """An exchange rate between two currencies.

    Stores the rate as a Decimal to maintain precision.
    ``updated_at`` tracks staleness of the rate.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "from_currency": "USD",
                    "to_currency": "CREDITS",
                    "rate": "100",
                    "updated_at": 1711699200.0,
                },
                {
                    "from_currency": "BTC",
                    "to_currency": "USD",
                    "rate": "60000.00",
                    "updated_at": 1711699200.0,
                },
            ]
        },
    )

    from_currency: Currency
    to_currency: Currency
    rate: Decimal
    updated_at: float = Field(default_factory=time.time)

    @field_serializer("rate")
    @classmethod
    def _serialize_rate(cls, v: Decimal) -> str:
        return str(v)
