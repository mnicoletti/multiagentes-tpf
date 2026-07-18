"""Nodos del grafo mínimo F2: parser → orquestador → analista de cartera."""

from __future__ import annotations

import json
import re
from decimal import Decimal

from langchain_core.messages import HumanMessage, SystemMessage

from portfoliosentinel.agents.cartera import CarteraLLMOutput
from portfoliosentinel.agents.prompts.cartera import (
    CARTERA_SYSTEM_PROMPT,
    build_cartera_user_message,
)
from portfoliosentinel.config.models import get_chat_model
from portfoliosentinel.graph.logging_utils import get_node_logger, log_json
from portfoliosentinel.graph.state import Diagnosis, PortfolioState, Snapshot
from portfoliosentinel.graph.weights import (
    cluster_coverage_gaps,
    compute_class_weights,
    compute_position_weights,
    materialize_clusters,
)
from portfoliosentinel.tools.parser import parse_account_statement

logger = get_node_logger("portfoliosentinel.graph.nodes")


class ClusterCoverageError(ValueError):
    """El LLM no cubrió todos los tickers del snapshot tras el reintento."""


def parser_node(state: PortfolioState) -> dict:
    """Nodo determinista: .xlsx → snapshot tipado (F1)."""
    run_id = state.get("run_id", "")
    inputs = state["inputs"]
    if not inputs.xlsx_path:
        raise ValueError("F2 requiere inputs.xlsx_path; el modo degradado sin .xlsx llega en F3")

    snapshot = parse_account_statement(inputs.xlsx_path)
    log_json(
        logger,
        "parser_done",
        run_id=run_id,
        positions=len(snapshot.positions),
        total_ars=str(snapshot.total_ars),
        mep_implied=str(snapshot.mep_implied),
        investor_alias=snapshot.investor_alias,
    )
    return {
        "snapshot": snapshot,
        "degraded_mode": False,
        "prev_snapshot": state.get("prev_snapshot"),
        "constraints": state.get("constraints") or [],
        "technical_readings": state.get("technical_readings") or [],
        "info_gaps": state.get("info_gaps") or [],
    }


def orchestrator_node(state: PortfolioState) -> dict:
    """Orquestador mínimo F2: valida snapshot y rutea al Analista de Cartera.

    Sin MCP todavía (F3): no lee BD ni hace echo-back de restricciones.
    """
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Orquestador: falta snapshot; el parser debió poblarlo")

    log_json(
        logger,
        "orchestrator_route",
        run_id=run_id,
        next="analista_cartera",
        degraded_mode=bool(state.get("degraded_mode", False)),
        constraints_count=len(state.get("constraints") or []),
        positions=len(snapshot.positions),
    )
    # F2: sin echo-back HITL ni store; solo confirma el camino feliz.
    return {
        "constraints": state.get("constraints") or [],
        "degraded_mode": False,
    }


def _fmt_pct(weight: Decimal) -> str:
    return f"{(weight * Decimal('100')).quantize(Decimal('0.01'))}%"


def _parse_cartera_json(raw: str) -> CarteraLLMOutput:
    """Fallback si with_structured_output no está disponible o falla con Ollama."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return CarteraLLMOutput.model_validate(json.loads(text))


def _assignments_from_llm(llm_out: CarteraLLMOutput) -> list[tuple[str, str, list[str]]]:
    return [(c.name, c.driver, c.tickers) for c in llm_out.clusters]


def _invoke_cartera_llm(model: object, user_msg: str) -> CarteraLLMOutput:
    llm_out: CarteraLLMOutput | None = None
    try:
        structured = model.with_structured_output(CarteraLLMOutput)  # type: ignore[attr-defined]
        result = structured.invoke(
            [
                SystemMessage(content=CARTERA_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ]
        )
        if isinstance(result, CarteraLLMOutput):
            llm_out = result
        elif isinstance(result, dict):
            llm_out = CarteraLLMOutput.model_validate(result)
    except Exception as exc:  # noqa: BLE001 — fallback JSON texto
        log_json(logger, "cartera_structured_fallback", error=str(exc))

    if llm_out is None:
        raw = model.invoke(  # type: ignore[attr-defined]
            [
                SystemMessage(content=CARTERA_SYSTEM_PROMPT),
                HumanMessage(
                    content=user_msg + "\n\nRespondé ÚNICAMENTE un JSON con keys: "
                    "clusters (list de {name,driver,tickers}), "
                    "concentrations (list str), structural_diagnosis (str). "
                    "Cada cluster debe tener tickers no vacío; cobertura total del snapshot."
                ),
            ]
        )
        content = raw.content if hasattr(raw, "content") else str(raw)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        llm_out = _parse_cartera_json(str(content))
    return llm_out


def _coverage_feedback(missing: set[str]) -> str:
    ordered = ", ".join(sorted(missing))
    return (
        f"\n\nCORRECCIÓN OBLIGATORIA: faltaron estos tickers en los clusters: {ordered}. "
        "Reasigná la partición completa. Cada ticker del snapshot en exactamente un cluster; "
        "ningún cluster vacío. Si falta VIST, ponelo en el cluster energético junto a YPFD "
        "(es CEDEAR de energía, no lo agrupes por sección CEDEARS)."
    )


def analista_cartera_node(state: PortfolioState) -> dict:
    """Analista de Cartera: pesos deterministas + clustering semántico vía LLM."""
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Analista de Cartera: falta snapshot")

    class_weights = compute_class_weights(snapshot)
    position_weights = compute_position_weights(snapshot)
    tickers_must_cover = ", ".join(p.ticker for p in snapshot.positions)

    positions_table = "\n".join(
        f"- {p.ticker} [{p.asset_class}] qty={p.quantity} price={p.price} total={p.total}"
        for p in snapshot.positions
    )
    class_table = "\n".join(
        f"- {c.asset_class}: {c.total_ars} ARS ({_fmt_pct(c.weight)})" for c in class_weights
    )
    pos_table = "\n".join(
        f"- {p.ticker}: {p.total_ars} ARS ({_fmt_pct(p.weight)})" for p in position_weights
    )

    user_msg = build_cartera_user_message(
        positions_table=positions_table,
        class_weights_table=class_table,
        position_weights_table=pos_table,
        mep_implied=str(snapshot.mep_implied),
        total_ars=str(snapshot.total_ars),
        total_usd=str(snapshot.total_usd),
        tickers_must_cover=tickers_must_cover,
    )

    model = get_chat_model("cartera")
    llm_out = _invoke_cartera_llm(model, user_msg)
    assignments = _assignments_from_llm(llm_out)
    gaps = cluster_coverage_gaps(snapshot, assignments)

    if gaps:
        log_json(
            logger,
            "cartera_coverage_retry",
            run_id=run_id,
            missing=sorted(gaps),
        )
        llm_out = _invoke_cartera_llm(model, user_msg + _coverage_feedback(gaps))
        assignments = _assignments_from_llm(llm_out)
        gaps = cluster_coverage_gaps(snapshot, assignments)

    if gaps:
        raise ClusterCoverageError(
            f"Clustering incompleto tras reintento; faltan tickers: {sorted(gaps)}"
        )

    clusters = materialize_clusters(snapshot, assignments, drop_empty=True)
    _assert_full_coverage_after_materialize(snapshot, clusters)

    diagnosis = Diagnosis(
        class_weights=class_weights,
        position_weights=position_weights,
        mep_implied=snapshot.mep_implied,
        clusters=clusters,
        concentrations=list(llm_out.concentrations),
        structural_diagnosis=llm_out.structural_diagnosis,
    )

    log_json(
        logger,
        "cartera_done",
        run_id=run_id,
        clusters=[c.name for c in clusters],
        diagnosis=diagnosis.structural_diagnosis,
    )
    return {"diagnosis": diagnosis}


def _assert_full_coverage_after_materialize(snapshot: Snapshot, clusters: list) -> None:
    assigned = {t for c in clusters for t in c.tickers}
    expected = {p.ticker.upper() for p in snapshot.positions}
    missing = expected - assigned
    if missing:
        raise ClusterCoverageError(
            f"Clustering incompleto tras materializar; faltan tickers: {sorted(missing)}"
        )
