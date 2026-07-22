"""Tests del enriquecimiento de cotizaciones desde el snapshot."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from portfoliosentinel.tools.schemas import AccountSnapshot, CashBalance, Position
from portfoliosentinel.tools.statement_market import (
    enrich_quotes_from_snapshot,
    fx_overlay_statement_mep,
)


def _snap() -> AccountSnapshot:
    return AccountSnapshot(
        investor_alias="INV-001",
        as_of=date(2026, 7, 21),
        cash=[
            CashBalance(currency="ARS", amount=Decimal("100")),
            CashBalance(currency="USD", amount=Decimal("10")),
        ],
        positions=[
            Position(
                ticker="GGAL",
                quantity=Decimal("1"),
                price=Decimal("7965"),
                total=Decimal("7965"),
                asset_class="ACCIONES",
            ),
            Position(
                ticker="NVDA",
                quantity=Decimal("2"),
                price=Decimal("13540"),
                total=Decimal("27080"),
                asset_class="CEDEARS",
            ),
        ],
        total_ars=Decimal("35145"),
        total_usd=Decimal("20"),
        mep_implied=Decimal("1757.25"),
    )


def test_enrich_applies_statement_prices_and_reports_missing():
    quotes = {
        "source": "fixture",
        "quotes": {"GGAL": {"last": 6400.0, "bid": 6380.0, "ask": 6420.0}},
    }
    out, missing = enrich_quotes_from_snapshot(quotes, _snap())
    assert missing == ["NVDA"]
    # Precios del estado pisan los del feed para tickers de la cartera.
    assert out["quotes"]["GGAL"]["last"] == 7965.0
    assert out["quotes"]["GGAL"]["source"] == "statement"
    assert out["quotes"]["NVDA"]["last"] == 13540.0
    assert out["quotes"]["NVDA"]["source"] == "statement"
    assert "statement" in out["source"]


def test_fx_overlay_uses_statement_mep():
    fx = {"source": "fixture", "rates": {"mep": {"compra": 1400.0, "venta": 1500.0, "mid": 1450.0}}}
    out = fx_overlay_statement_mep(fx, Decimal("1509.845"))
    assert out["rates"]["mep"]["mid"] == 1509.845
    assert out["rates"]["mep"]["source"] == "statement"
