"""Modelos Pydantic v2 del snapshot de cartera (salida del parser)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetClass = Literal["ACCIONES", "BONOS", "CEDEARS"]
CurrencyCode = Literal["ARS", "USD"]


def _as_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class CashBalance(BaseModel):
    """Saldo en moneda (sección MONEDAS)."""

    model_config = ConfigDict(extra="forbid")

    currency: CurrencyCode
    amount: Decimal

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class Position(BaseModel):
    """Posición individual valorizada en ARS."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    quantity: Decimal
    price: Decimal
    total: Decimal
    asset_class: AssetClass

    @field_validator("quantity", "price", "total", mode="before")
    @classmethod
    def _coerce_money(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class AccountSnapshot(BaseModel):
    """Snapshot tipado post-scrubbing. Sin PII: solo alias INV-001."""

    model_config = ConfigDict(extra="forbid")

    investor_alias: str = Field(description="Alias post-scrubbing; siempre INV-001")
    as_of: date | None = None
    cash: list[CashBalance]
    positions: list[Position]
    total_ars: Decimal
    total_usd: Decimal
    mep_implied: Decimal = Field(description="ARS total / USD total, sin redondeo")

    @field_validator("total_ars", "total_usd", "mep_implied", mode="before")
    @classmethod
    def _coerce_totals(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]
