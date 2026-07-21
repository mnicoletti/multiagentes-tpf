"""Armado determinista del informe (skip_llm / DoD F6)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfoliosentinel.graph.state import (
    Constraint,
    Diagnosis,
    InfoGap,
    MarketContext,
    PortfolioState,
    RebalancePlan,
    Snapshot,
    StalenessInfo,
    TechnicalReading,
)

DISCLAIMER = "Este sistema no constituye asesoramiento financiero y no ejecuta órdenes."

SECTION_HEADINGS = (
    "## 1. Encabezado",
    "## 2. Radiografía",
    "## 3. Análisis por instrumento",
    "## 4. Integración FCI",
    "## 5. Screening de activos nuevos",
    "## 6. Solicitud de gráficos",
    "## 7. Plan de acción consolidado",
)


def _dec(v: Decimal | None) -> str:
    if v is None:
        return "n/a"
    return format(v, "f")


def _fmt_pct(weight: Decimal) -> str:
    return f"{(weight * Decimal('100')).quantize(Decimal('0.01'))}%"


def _action_line(ticker: str, action: str, qty: Decimal | None, ref: str) -> str:
    qty_s = "null" if qty is None else format(qty, "f")
    return f"- ticker={ticker}; action={action}; qty={qty_s}; ref={ref}"


def build_deterministic_report(
    *,
    run_id: str,
    snapshot: Snapshot,
    constraints: list[Constraint],
    diagnosis: Diagnosis | None,
    market_context: MarketContext | None,
    technical_readings: list[TechnicalReading],
    plan: RebalancePlan | None,
    info_gaps: list[InfoGap],
    capital_new_ars: Decimal | None,
    degraded_mode: bool = False,
    staleness: StalenessInfo | None = None,
) -> str:
    """Informe completo §6.3 con marcadores que el linter verifica."""
    confirmed = [c for c in constraints if c.status == "active" and c.confirmed]
    confirmed_lines = (
        "\n".join(f"- {c.rule}" + (f" ({c.ticker})" if c.ticker else "") for c in confirmed)
        or "- (ninguna restricción activa)"
    )

    capital = _dec(capital_new_ars) if capital_new_ars is not None else "0"
    mep = _dec(snapshot.mep_implied)
    mep_mkt = _dec(market_context.mep_market) if market_context else "n/a"
    mep_warn = (
        market_context.mep_warning
        if market_context and market_context.mep_warning
        else "(sin warning MEP)"
    )

    lines: list[str] = [
        f"# Informe PortfolioSentinel — run_id={run_id}",
        "",
        SECTION_HEADINGS[0],
        f"- Alias: {snapshot.investor_alias}",
        f"- Total ARS: {_dec(snapshot.total_ars)} (ref=snapshot)",
        f"- Total USD: {_dec(snapshot.total_usd)} (ref=snapshot)",
        f"- MEP implícito: {mep} (ref=snapshot)",
        f"- MEP mercado: {mep_mkt} (ref=market-data)",
        f"- Capital nuevo ARS: {capital}",
        "- Activos externos / FCI: ver §4",
        f"- MEP check: {mep_warn}",
        "",
        f"**Descargo:** {DISCLAIMER}",
        "",
        "**Requisitos confirmados:**",
        confirmed_lines,
        "",
        "**Decisiones de diseño propuestas:**",
        "- Clustering por driver de riesgo y umbrales de concentración (criterio del analista).",
        "- Priorización de mitigaciones alternativas cuando hay restricción dura.",
    ]

    if degraded_mode and staleness is not None:
        lines.extend(["", f"> Modo degradado: {staleness.warning}"])

    lines.extend(["", SECTION_HEADINGS[1]])
    if diagnosis is not None:
        lines.append(f"Diagnóstico estructural: {diagnosis.structural_diagnosis}")
        lines.append("")
        lines.append("Pesos por clase (ref=snapshot):")
        for cw in diagnosis.class_weights:
            lines.append(f"- {cw.asset_class}: {_dec(cw.total_ars)} ARS ({_fmt_pct(cw.weight)})")
        lines.append("")
        lines.append("Concentraciones:")
        for note in diagnosis.concentrations or ["(sin notas)"]:
            lines.append(f"- {note}")
        lines.append("")
        lines.append("Clusters (pesos deterministas; nombres/drivers propuestos):")
        for cl in diagnosis.clusters:
            lines.append(
                f"- {cl.name} [{cl.driver}]: {', '.join(cl.tickers)} — "
                f"{_dec(cl.total_ars)} ARS ({_fmt_pct(cl.weight)})"
            )
    else:
        lines.append("(sin diagnóstico de cartera en esta corrida)")

    lines.extend(["", SECTION_HEADINGS[2]])
    if plan is not None:
        # Agrupar por acción como "bloques"
        by_action: dict[str, list[Any]] = {}
        for a in plan.actions:
            by_action.setdefault(a.action, []).append(a)
        for action_kind, acts in by_action.items():
            lines.append(f"### Bloque: {action_kind}")
            for a in acts:
                qty = f" qty={_dec(a.quantity)}" if a.quantity is not None else ""
                stop = f" stop={_dec(a.stop_level)}" if a.stop_level is not None else ""
                lines.append(f"- **{a.ticker}**{qty}{stop} — {a.rationale}")
                if a.risk_notes:
                    lines.append(f"  - Riesgo: {'; '.join(a.risk_notes)}")
                if a.mitigations:
                    lines.append(f"  - Mitigaciones: {'; '.join(a.mitigations)}")
                lines.append("  - Trazabilidad: ref=plan+snapshot")
    else:
        lines.append("(sin plan aprobado)")

    if market_context is not None:
        lines.append("")
        lines.append(f"Contexto de mercado: {market_context.summary}")
        if market_context.citations:
            lines.append("Citas:")
            for c in market_context.citations[:8]:
                lines.append(f"- [{c.get('source_id')}] {c.get('note')} (ref=cita)")

    lines.extend(["", SECTION_HEADINGS[3]])
    fci = [
        r
        for r in technical_readings
        if "fci" in (r.purpose or "").lower()
        or "fci" in r.image_path.lower()
        or "tenencia_externa" in (r.purpose or "").lower()
    ]
    if fci:
        for r in fci:
            lines.append(f"- {r.summary} (ref=técnica:{r.image_path})")
            if r.verdict:
                lines.append(f"  - Veredicto propuesto: {r.verdict}")
    else:
        lines.append(
            "- Sin panel FCI en esta corrida; la tenencia externa queda sin lectura multimodal."
        )

    lines.extend(["", SECTION_HEADINGS[4]])
    screening = [
        r
        for r in technical_readings
        if "screening" in (r.purpose or "").lower() or "screening" in r.image_path.lower()
    ]
    if screening:
        for r in screening:
            lines.append(
                f"- {r.ticker or 'activo'}: {r.summary} "
                f"(veredicto propuesto: {r.verdict}; ref=técnica)"
            )
    else:
        lines.append("- Sin screening de activos nuevos en los inputs de esta corrida.")

    lines.extend(["", SECTION_HEADINGS[5]])
    gap_list = list(info_gaps)
    pending_stops = [r for r in technical_readings if r.needs_stop_level and r.stop_level is None]
    if gap_list or pending_stops:
        for g in gap_list:
            lines.append(f"- Gap {g.ticker or '?'}: {g.detail}")
        for r in pending_stops:
            lines.append(
                f"- Falta gráfico ampliado para stop de {r.ticker} "
                f"(propósito declarado: {r.purpose}). No se inventa el nivel."
            )
    else:
        lines.append(
            "- Sin solicitud pendiente de gráficos: stops disponibles están cubiertos "
            "o no aplican en esta corrida."
        )

    lines.extend(["", SECTION_HEADINGS[6]])
    if plan is not None:
        lines.append(plan.reasoning or plan.notes or "")
        if plan.capital_allocation:
            lines.append("")
            lines.append("Asignación de capital nuevo (propuesta):")
            for row in plan.capital_allocation:
                lines.append(f"- {row}")
        if plan.calculator_result:
            resulting = plan.calculator_result.get("resulting_cluster_weights") or []
            if resulting:
                lines.append("")
                lines.append("Pesos resultantes por cluster (ref=calculadora):")
                for row in resulting:
                    if isinstance(row, dict):
                        lines.append(
                            f"- {row.get('name')}: {row.get('total_ars')} ARS "
                            f"(weight={row.get('weight')})"
                        )
        lines.append("")
        lines.append("### Acciones_verificables")
        for a in plan.actions:
            ref_parts = ["snapshot"]
            if a.ticker and any(
                c.ticker and c.ticker.upper() == a.ticker.upper() for c in confirmed
            ):
                ref_parts.append(f"restricción:no vender {a.ticker}")
            if a.ml_signal_cited:
                ref_parts.append("ml:predict_trend")
            lines.append(_action_line(a.ticker, a.action, a.quantity, "+".join(ref_parts)))
        if plan.ml_inputs:
            lines.append("")
            lines.append("Insumos ML citados (no decisión):")
            for m in plan.ml_inputs:
                lines.append(f"- {m.note}")
    else:
        lines.append("(sin plan)")
        lines.append("")
        lines.append("### Acciones_verificables")
        lines.append("- ticker=NONE; action=mantener; qty=null; ref=none")

    lines.extend(
        [
            "",
            "**Próximo paso:** revisar el plan consolidado; el sistema no ejecuta órdenes.",
            "",
            f"**Descargo (cierre):** {DISCLAIMER}",
        ]
    )
    return "\n".join(lines)


def build_report_from_state(state: PortfolioState) -> str:
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Redactor: falta snapshot")
    inputs = state["inputs"]
    return build_deterministic_report(
        run_id=state.get("run_id", ""),
        snapshot=snapshot,
        constraints=list(state.get("constraints") or []),
        diagnosis=state.get("diagnosis"),
        market_context=state.get("market_context"),
        technical_readings=list(state.get("technical_readings") or []),
        plan=state.get("plan"),
        info_gaps=list(state.get("info_gaps") or []),
        capital_new_ars=inputs.capital_new_ars,
        degraded_mode=bool(state.get("degraded_mode", False)),
        staleness=state.get("staleness"),
    )
