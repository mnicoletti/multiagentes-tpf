"""Verificación cruzada de MEP (SPEC §6.2): implícito del xlsx vs market-data."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfoliosentinel.config.settings import MEP_DIVERGENCE_THRESHOLD_PCT


def mep_mid_from_fx(fx: dict[str, Any]) -> Decimal:
    """Extrae el mid MEP de la respuesta de get_fx_rates."""
    rates = fx.get("rates") or {}
    mep = rates.get("mep") or {}
    if "mid" in mep:
        return Decimal(str(mep["mid"]))
    compra = mep.get("compra")
    venta = mep.get("venta")
    if compra is None or venta is None:
        raise ValueError("FX sin MEP usable (faltan mid/compra/venta)")
    return (Decimal(str(compra)) + Decimal(str(venta))) / Decimal("2")


def check_mep_divergence(
    mep_implied: Decimal,
    mep_market: Decimal,
    *,
    threshold_pct: float | None = None,
) -> dict[str, Any]:
    """Compara MEP implícito vs mercado. Divergencia > umbral → warning.

    Retorna dict con campos para MarketContext (sin inventar números).
    """
    thr = Decimal(str(threshold_pct if threshold_pct is not None else MEP_DIVERGENCE_THRESHOLD_PCT))
    if mep_implied == 0:
        raise ValueError("MEP implícito no puede ser cero")
    divergence_pct = abs(mep_market - mep_implied) / mep_implied * Decimal("100")
    exceeds = divergence_pct > thr
    warning: str | None = None
    if exceeds:
        warning = (
            f"Divergencia de MEP: implícito={mep_implied} vs mercado={mep_market} "
            f"({divergence_pct.quantize(Decimal('0.01'))}% > umbral {thr}%). "
            "Revisar coherencia de valuación ARS/USD antes de acciones con nominales finos."
        )
    return {
        "mep_implied": mep_implied,
        "mep_market": mep_market,
        "mep_divergence_pct": divergence_pct,
        "threshold_pct": thr,
        "exceeds_threshold": exceeds,
        "mep_warning": warning,
    }
