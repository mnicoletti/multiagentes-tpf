"""Reglas deterministas del revisor A2A (2–3 checks; no sustituyen al validator interno)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Umbral consultivo de concentración por cluster (no hard constraint del usuario).
CLUSTER_WEIGHT_WARN = Decimal("0.35")

# Acciones que tipicamente requieren stop documentado.
_STOP_ACTIONS = frozenset({"vender", "reducir", "tomar_ganancia_parcial", "salir"})


def apply_compliance_rules(plan_payload: dict[str, Any]) -> list[str]:
    """Devuelve observaciones consultivas. Vacío = sin hallazgos de reglas."""
    observations: list[str] = []
    actions = list(plan_payload.get("actions") or [])
    clusters = list(plan_payload.get("cluster_weights") or [])
    restricted = {str(t).upper() for t in (plan_payload.get("restricted_tickers") or [])}

    for row in clusters:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("cluster") or "?")
        raw_w = row.get("weight")
        if raw_w is None:
            continue
        try:
            weight = Decimal(str(raw_w))
        except Exception:  # noqa: BLE001
            continue
        if weight > CLUSTER_WEIGHT_WARN:
            pct = (weight * Decimal("100")).quantize(Decimal("0.01"))
            observations.append(
                f"Concentración consultiva: cluster '{name}' al {pct}% "
                f"(umbral aviso {CLUSTER_WEIGHT_WARN * 100}%)."
            )

    for action in actions:
        if not isinstance(action, dict):
            continue
        ticker = str(action.get("ticker") or "").upper()
        kind = str(action.get("action") or "").lower()
        if ticker and ticker in restricted and kind in {"vender", "salir"}:
            observations.append(
                f"Plan incluye '{kind}' sobre restringido {ticker} "
                "(el validator interno debería haberlo bloqueado; aviso consultivo)."
            )
        if kind in _STOP_ACTIONS and action.get("stop_level") in (None, "", "null"):
            observations.append(
                f"Acción '{kind}' en {ticker or '?'} sin stop_level documentado "
                "(recomendación consultiva: adjuntar gráfico o nivel)."
            )

    return observations
