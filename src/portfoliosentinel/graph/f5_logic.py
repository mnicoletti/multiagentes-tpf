"""Lógica determinista F5 (stubs sin LLM + armado de planes GC-2).

Usada por tests DoD y por nodos con skip_llm=True. El camino LLM llama a esto
como fallback / post-proceso de calculadora + gaps.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from portfoliosentinel.graph.state import (
    Constraint,
    Diagnosis,
    InfoGap,
    MlSignalCitation,
    PlanAction,
    RebalancePlan,
    Snapshot,
    TechnicalReading,
)
from portfoliosentinel.tools.calc import compute_rebalance, trades_from_plan_actions
from portfoliosentinel.tools.ml_trend import TrendFeatures, predict_trend

# Features de demostración por ticker (insumo ML; no precios de tenencia).
_DEMO_FEATURES: dict[str, TrendFeatures] = {
    "GGAL": TrendFeatures(
        rsi_14=62.0, macd_hist=0.45, sma_slope=0.02, return_5d=0.03, volume_z=0.5
    ),
    "YPFD": TrendFeatures(
        rsi_14=48.0, macd_hist=-0.1, sma_slope=0.0, return_5d=-0.01, volume_z=-0.2
    ),
    "VIST": TrendFeatures(rsi_14=55.0, macd_hist=0.2, sma_slope=0.01, return_5d=0.02, volume_z=0.1),
    "AAPL": TrendFeatures(rsi_14=50.0, macd_hist=0.0, sma_slope=0.0, return_5d=0.0, volume_z=0.0),
}


def _restricted_tickers(constraints: list[Constraint]) -> set[str]:
    out: set[str] = set()
    for c in constraints:
        if c.status != "active":
            continue
        if c.ticker:
            out.add(c.ticker.upper())
    return out


def _qty(snapshot: Snapshot, ticker: str) -> Decimal:
    for p in snapshot.positions:
        if p.ticker.upper() == ticker.upper():
            return p.quantity
    return Decimal("0")


def stub_technical_readings(
    image_paths: list[str],
    image_purposes: dict[str, str],
    *,
    resume_stop_levels: dict[str, Decimal] | None = None,
) -> list[TechnicalReading]:
    """Lecturas sin visión LLM: parsea propósito + nombre de archivo."""
    resume_stop_levels = resume_stop_levels or {}
    readings: list[TechnicalReading] = []
    for path in image_paths:
        purpose = image_purposes.get(path) or image_purposes.get(Path(path).name) or "unspecified"
        name = Path(path).name.lower()
        ticker = None
        for cand in ("GGAL", "YPFD", "VIST", "AAPL", "MELI", "SPY", "AL30", "GD30"):
            if cand.lower() in name:
                ticker = cand
                break
        m = re.search(r"([A-Z]{2,5})", Path(path).stem.upper())
        if ticker is None and m:
            ticker = m.group(1)

        stop_level: Decimal | None = None
        needs_stop = False
        # Visibilidad del nivel: solo archivo with-stop o resume HITL.
        # El purpose "stop_chart" NO implica que el nivel sea legible.
        stop_visible = "with-stop" in name
        if ticker and ticker in resume_stop_levels:
            stop_level = resume_stop_levels[ticker]
            stop_visible = True
        elif stop_visible and ticker == "GGAL":
            stop_level = Decimal("6200")

        purpose_wants_stop = any(
            k in purpose.lower() for k in ("stop_chart", "fix_stop", "grafico_stop", "stop")
        )
        if stop_level is None and (purpose_wants_stop or "no-stop" in name):
            needs_stop = True

        # Panel FCI
        if "fci" in name or "tenencia_externa" in purpose:
            readings.append(
                TechnicalReading(
                    image_path=path,
                    purpose=purpose,
                    ticker=None,
                    summary=(
                        "Panel FCI sintético: curva de patrimonio alcista suave; "
                        "rol liquidez-vs-retorno. Propósito declarado: tenencia externa."
                    ),
                    trend="up",
                    indicators={"rend_30d_pct": 1.8, "rend_ytd_pct": 12.1},
                    verdict="mantener_como_liquidez",
                    needs_stop_level=False,
                    stop_level=None,
                )
            )
            continue

        if "screening" in purpose or "screening" in name:
            readings.append(
                TechnicalReading(
                    image_path=path,
                    purpose=purpose,
                    ticker=ticker,
                    summary=f"Screening de {ticker or 'activo'}: estructura lateral/neutra.",
                    trend="sideways",
                    indicators={"rsi": 50, "macd_hist": 0.0},
                    verdict="no_priorizar_compra",
                    needs_stop_level=False,
                )
            )
            continue

        readings.append(
            TechnicalReading(
                image_path=path,
                purpose=purpose,
                ticker=ticker,
                summary=(
                    f"Gráfico de {ticker or '?'}: tendencia visible; "
                    + (
                        f"stop legible en {stop_level}."
                        if stop_level is not None
                        else "sin nivel de stop ampliado legible."
                    )
                ),
                trend="up" if ticker == "GGAL" else "sideways",
                indicators={"rsi": 58, "macd_hist": 0.4},
                verdict="definir_stop_antes_de_tomar_ganancia" if needs_stop else "ok",
                needs_stop_level=needs_stop and stop_level is None,
                stop_level=stop_level,
            )
        )
    return readings


def collect_ml_signals(tickers: list[str]) -> list[MlSignalCitation]:
    citations: list[MlSignalCitation] = []
    for t in tickers:
        feats = _DEMO_FEATURES.get(
            t.upper(),
            TrendFeatures(rsi_14=50.0, macd_hist=0.0, sma_slope=0.0, return_5d=0.0, volume_z=0.0),
        )
        pred = predict_trend(feats)
        citations.append(
            MlSignalCitation(
                ticker=t.upper(),
                label=pred.label,
                proba=pred.proba,
                role="insumo",
                note=(
                    f"predict_trend={pred.label} (p={pred.proba:.2f}) "
                    f"v{pred.model_version} — insumo, no decisión"
                ),
            )
        )
    return citations


def build_deterministic_plan(
    *,
    snapshot: Snapshot,
    constraints: list[Constraint],
    diagnosis: Diagnosis | None,
    technical_readings: list[TechnicalReading],
    capital_new_ars: Decimal | None,
    validation_feedback: list[str] | None = None,
    force_illegal_sell: str | None = None,
) -> tuple[RebalancePlan, list[InfoGap]]:
    """Plan determinista para DoD / skip_llm.

    GC-2: si YPFD (u otro) está restringido, NO lo vende; reduce VIST del cluster
    energético y señala riesgo + mitigaciones.

    `force_illegal_sell`: planta una venta ilegal (para test de validator→replan).
    """
    restricted = _restricted_tickers(constraints)
    feedback = validation_feedback or []
    # Si el validator ya rechazó una venta ilegal, no la repetimos.
    avoid_illegal = any("no-sell-restricted" in f or "restringido" in f for f in feedback)

    ml_inputs = collect_ml_signals(["GGAL", "YPFD", "VIST"])
    ml_by = {m.ticker: m for m in ml_inputs}

    actions: list[PlanAction] = []
    gaps: list[InfoGap] = []

    ggal_qty = _qty(snapshot, "GGAL")
    vist_qty = _qty(snapshot, "VIST")

    # Lecturas técnicas → stops / gaps
    stop_by_ticker: dict[str, Decimal] = {}
    needs_stop: set[str] = set()
    for r in technical_readings:
        if r.ticker and r.stop_level is not None:
            stop_by_ticker[r.ticker.upper()] = r.stop_level
        if r.ticker and r.needs_stop_level and r.stop_level is None:
            needs_stop.add(r.ticker.upper())

    # Tentación GC-2: "óptimo aparente" sería vender YPFD por concentración energética.
    # El plan correcto: NO vender YPFD; mitigar vía VIST + capital nuevo.
    if force_illegal_sell and not avoid_illegal:
        illegal = force_illegal_sell.upper()
        actions.append(
            PlanAction(
                ticker=illegal,
                action="salir",
                quantity=_qty(snapshot, illegal),
                pct_of_position=Decimal("1"),
                rationale="PLANTA DE TEST: venta ilegal para provocar validator",
                risk_notes=["forzado"],
            )
        )

    if "YPFD" in restricted or (diagnosis and "YPFD" in (diagnosis.structural_diagnosis or "")):
        # Siempre señalar riesgo del restringido sin venderlo.
        actions.append(
            PlanAction(
                ticker="YPFD",
                action="mantener",
                quantity=None,
                rationale=(
                    "Restricción activa 'no vender YPFD': se mantiene la posición. "
                    f"Insumo ML: {ml_by.get('YPFD').note if 'YPFD' in ml_by else 'n/a'}."
                ),
                ml_signal_cited=True,
                risk_notes=[
                    "Concentración energética (YPFD+VIST) sigue siendo un riesgo estructural "
                    "aunque no se pueda vender YPFD."
                ],
                mitigations=[
                    "Reducir VIST (mismo driver) en lugar de YPFD",
                    "Asignar capital nuevo fuera del cluster energético",
                ],
            )
        )
        if vist_qty > 0:
            # Mitigación: vender parte/todo VIST
            actions.append(
                PlanAction(
                    ticker="VIST",
                    action="salir",
                    quantity=vist_qty,
                    pct_of_position=Decimal("1"),
                    rationale=(
                        "Mitigación alternativa a no poder vender YPFD: "
                        "salir de VIST (mismo cluster energético). "
                        f"Insumo ML VIST: {ml_by['VIST'].note}."
                    ),
                    ml_signal_cited=True,
                    risk_notes=["Reduce exposición al driver energía argentina"],
                    mitigations=[],
                )
            )

    # GGAL: sobreconcentración → toma parcial, pero stop requiere gráfico
    if ggal_qty > 0:
        partial = (ggal_qty * Decimal("0.10")).quantize(Decimal("1"))
        if partial <= 0:
            partial = min(Decimal("1"), ggal_qty)
        ggal_stop = stop_by_ticker.get("GGAL")
        if "GGAL" in needs_stop and ggal_stop is None:
            gaps.append(
                InfoGap(
                    kind="missing_stop_chart",
                    ticker="GGAL",
                    detail=(
                        "Falta gráfico ampliado para fijar stop de GGAL. "
                        "Prohibido inventar el nivel; se solicita vía interrupt()."
                    ),
                )
            )
            actions.append(
                PlanAction(
                    ticker="GGAL",
                    action="tomar_ganancia_parcial",
                    quantity=partial,
                    pct_of_position=Decimal("0.10"),
                    rationale=(
                        "Sobreconcentración GGAL (~66%): toma parcial condicionada a stop. "
                        f"Insumo ML: {ml_by['GGAL'].note}. Stop pendiente (info_gap)."
                    ),
                    stop_level=None,
                    ml_signal_cited=True,
                    risk_notes=["Stop no definido — no se inventa nivel"],
                )
            )
        else:
            actions.append(
                PlanAction(
                    ticker="GGAL",
                    action="tomar_ganancia_parcial",
                    quantity=partial,
                    pct_of_position=Decimal("0.10"),
                    rationale=(
                        "Sobreconcentración GGAL: toma parcial con stop confirmado. "
                        f"Insumo ML: {ml_by['GGAL'].note}."
                    ),
                    stop_level=ggal_stop,
                    ml_signal_cited=True,
                )
            )

    # Resto: mantener
    covered = {a.ticker.upper() for a in actions}
    for p in snapshot.positions:
        if p.ticker.upper() in covered:
            continue
        if p.ticker.upper() in restricted:
            actions.append(
                PlanAction(
                    ticker=p.ticker,
                    action="mantener",
                    rationale=f"Restricción activa sobre {p.ticker}: mantener.",
                    risk_notes=[f"Restricción no vender {p.ticker}"],
                    mitigations=["Diversificar con capital nuevo u otros tickers del cluster"],
                )
            )
        else:
            actions.append(
                PlanAction(
                    ticker=p.ticker,
                    action="mantener",
                    rationale=f"Sin catalizador de cambio para {p.ticker}.",
                )
            )

    capital_allocation: list[dict[str, Any]] = []
    if capital_new_ars and capital_new_ars > 0:
        capital_allocation.append(
            {
                "destination": "BONOS_HD",
                "amount_ars": str(capital_new_ars),
                "note": "Capital nuevo fuera del cluster energético (mitigación)",
            }
        )

    trades = trades_from_plan_actions(actions)
    calc = compute_rebalance(
        snapshot,
        trades,
        capital_new_ars=capital_new_ars,
        clusters=list(diagnosis.clusters) if diagnosis else None,
    )

    reasoning = (
        "Plan armado combinando diagnóstico, mercado/técnico, restricciones y capital nuevo. "
        "predict_trend entra como insumo citado (ml_inputs / ml_signal_cited), "
        "no como conclusión autónoma. "
        + " ".join(m.note for m in ml_inputs)
        + (" Feedback validator aplicado: " + "; ".join(feedback) if feedback else "")
    )

    plan = RebalancePlan(
        actions=actions,
        capital_allocation=capital_allocation,
        calculator_result=calc.model_dump(mode="json"),
        ml_inputs=ml_inputs,
        notes="Plan determinístico F5 (skip_llm / DoD).",
        reasoning=reasoning,
    )
    return plan, gaps
