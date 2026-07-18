"""Valores esperados hardcodeados del golden parse de la fixture sintética."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

INVESTOR_ALIAS = "INV-001"
AS_OF = date(2026, 7, 15)

CASH_ARS = Decimal("2000000.00")
CASH_USD = Decimal("3000.00")

POSITIONS = [
    {
        "ticker": "GGAL",
        "quantity": Decimal("2500"),
        "price": Decimal("6400.00"),
        "total": Decimal("16000000.00"),
        "asset_class": "ACCIONES",
    },
    {
        "ticker": "YPFD",
        "quantity": Decimal("100"),
        "price": Decimal("25000.00"),
        "total": Decimal("2500000.00"),
        "asset_class": "ACCIONES",
    },
    {
        "ticker": "AL30",
        "quantity": Decimal("200"),
        "price": Decimal("7500.00"),
        "total": Decimal("1500000.00"),
        "asset_class": "BONOS",
    },
    {
        "ticker": "GD30",
        "quantity": Decimal("100"),
        "price": Decimal("8000.00"),
        "total": Decimal("800000.00"),
        "asset_class": "BONOS",
    },
    {
        "ticker": "AAPL",
        "quantity": Decimal("30"),
        "price": Decimal("20000.00"),
        "total": Decimal("600000.00"),
        "asset_class": "CEDEARS",
    },
    {
        "ticker": "MELI",
        "quantity": Decimal("20"),
        "price": Decimal("30000.00"),
        "total": Decimal("600000.00"),
        "asset_class": "CEDEARS",
    },
    {
        "ticker": "VIST",
        "quantity": Decimal("10"),
        "price": Decimal("10000.00"),
        "total": Decimal("100000.00"),
        "asset_class": "CEDEARS",
    },
    {
        "ticker": "SPY",
        "quantity": Decimal("5"),
        "price": Decimal("20000.00"),
        "total": Decimal("100000.00"),
        "asset_class": "CEDEARS",
    },
]

TOTAL_ARS = Decimal("24200000.00")
TOTAL_USD = Decimal("20000.00")
MEP_IMPLIED = Decimal("1210")  # 24200000 / 20000

# Sobreconcentración plantada: GGAL / TOTAL_ARS
GGAL_WEIGHT = Decimal("16000000.00") / TOTAL_ARS  # ~66.12%
