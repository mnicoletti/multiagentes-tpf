"""Completar cotizaciones/FX con precios del snapshot (estado de cuenta).

Arquitectura: market-data-mcp puede servir live (dolarapi/panel) o fixture.
Cuando faltan tickers (cartera propia con papeles nuevos), se rellenan con
`position.price` del parser — sin lista humana ni HITL (ADR-0010 / SPEC).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from portfoliosentinel.tools.schemas import AccountSnapshot


def enrich_quotes_from_snapshot(
    quotes: dict[str, Any],
    snapshot: AccountSnapshot,
) -> tuple[dict[str, Any], list[str]]:
    """Aplica precios del snapshot a todos los tickers de la cartera.

    Los precios del estado son la valuación del día del .xlsx. Devuelve además
    la lista de tickers que *faltaban* en la respuesta de market-data (papeles
    nuevos), para decidir si overlayar el MEP implícito.
    """
    out = dict(quotes)
    qmap: dict[str, Any] = dict(out.get("quotes") or {})
    missing: list[str] = []
    for pos in snapshot.positions:
        key = pos.ticker.upper()
        existing = qmap.get(key) or qmap.get(pos.ticker)
        if existing is None or existing.get("last") is None:
            missing.append(key)
        qmap[key] = {
            "last": float(pos.price),
            "bid": None,
            "ask": None,
            "change_pct": None,
            "source": "statement",
        }
    out["quotes"] = qmap
    if snapshot.positions:
        sources = out.get("source")
        if sources and sources != "statement":
            out["source"] = f"{sources}+statement"
        elif not sources:
            out["source"] = "statement"
        if snapshot.as_of is not None:
            out["as_of"] = snapshot.as_of.isoformat()
    return out, missing


def fx_overlay_statement_mep(
    fx: dict[str, Any],
    mep_implied: Decimal,
) -> dict[str, Any]:
    """Usa el MEP implícito del estado como mid de mercado (valuación del día del xlsx)."""
    out = dict(fx)
    rates = dict(out.get("rates") or {})
    mep = dict(rates.get("mep") or {})
    mid = float(mep_implied)
    mep["mid"] = mid
    mep.setdefault("compra", mid)
    mep.setdefault("venta", mid)
    mep["source"] = "statement"
    rates["mep"] = mep
    out["rates"] = rates
    prev = out.get("source")
    out["source"] = f"{prev}+statement" if prev and prev != "statement" else "statement"
    if "as_of" not in out or not out["as_of"]:
        out["as_of"] = datetime.now(UTC).isoformat()
    return out


def statement_as_of_iso(snapshot: AccountSnapshot) -> str:
    if snapshot.as_of is not None:
        return snapshot.as_of.isoformat()
    return date.today().isoformat()
