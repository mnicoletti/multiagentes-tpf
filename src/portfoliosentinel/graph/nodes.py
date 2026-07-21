"""Nodos del grafo: intake → orquestador → cartera → mercado → persist (F4)."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from mcp_servers.market_data.client import get_fx_rates, get_quotes
from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.agents.cartera import CarteraLLMOutput
from portfoliosentinel.agents.mercado import MercadoCitation, MercadoLLMOutput
from portfoliosentinel.agents.prompts.cartera import (
    CARTERA_SYSTEM_PROMPT,
    build_cartera_user_message,
)
from portfoliosentinel.agents.prompts.mercado import (
    MERCADO_SYSTEM_PROMPT,
    build_mercado_user_message,
)
from portfoliosentinel.config.models import get_chat_model
from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR
from portfoliosentinel.graph.logging_utils import get_node_logger, log_json
from portfoliosentinel.graph.state import (
    Constraint,
    Diagnosis,
    MarketContext,
    PortfolioState,
    Snapshot,
    StalenessInfo,
)
from portfoliosentinel.graph.weights import (
    cluster_coverage_gaps,
    compute_class_weights,
    compute_position_weights,
    materialize_clusters,
)
from portfoliosentinel.rag.ingest import ensure_knowledge_ingested, ingest_report
from portfoliosentinel.rag.retriever import format_hits_as_untrusted_context, retrieve
from portfoliosentinel.tools.mep_check import check_mep_divergence, mep_mid_from_fx
from portfoliosentinel.tools.parser import parse_account_statement
from portfoliosentinel.tools.portfolio_store import (
    snapshot_from_store_dict,
    snapshot_to_store_dict,
)
from portfoliosentinel.tools.web_search import web_search

logger = get_node_logger("portfoliosentinel.graph.nodes")


class ClusterCoverageError(ValueError):
    """El LLM no cubrió todos los tickers del snapshot tras el reintento."""


class MissingSnapshotError(ValueError):
    """Modo degradado sin snapshot previo en el store de dominio."""


def _parse_constraints_from_text(text: str | None) -> list[Constraint]:
    """Heurística mínima: 'no vender TICKER' → restricción dura."""
    if not text or not text.strip():
        return []
    found: list[Constraint] = []
    for match in re.finditer(r"no\s+vender\s+([A-Za-z0-9.]+)", text, flags=re.IGNORECASE):
        ticker = match.group(1).upper()
        found.append(
            Constraint(
                rule=f"no vender {ticker}",
                ticker=ticker,
                status="pending_confirmation",
                source="run",
                confirmed=False,
            )
        )
    return found


def _staleness_warning(snapshot_ts: str | None, as_of: date | None) -> str:
    label = as_of.strftime("%d/%m") if as_of else (snapshot_ts or "fecha desconocida")
    if snapshot_ts and as_of is None:
        # ts ISO → DD/MM si se puede
        try:
            label = date.fromisoformat(snapshot_ts[:10]).strftime("%d/%m")
        except ValueError:
            label = snapshot_ts[:10]
    return (
        f"análisis sobre snapshot del {label} — "
        "precios/tenencias posiblemente desactualizados; "
        "acciones con cantidades finas condicionadas/bloqueadas"
    )


def intake_node(state: PortfolioState, *, store: PortfolioStore) -> dict:
    """Intake F3: lee BD siempre; parsea .xlsx o carga último snapshot (degraded)."""
    run_id = state.get("run_id", "")
    inputs = state["inputs"]

    last_row = store.read_last_snapshot()
    prev_snapshot: Snapshot | None = None
    last_meta: dict[str, Any] | None = None
    if last_row is not None:
        prev_snapshot = snapshot_from_store_dict(last_row["data"])
        last_meta = {
            "id": last_row["id"],
            "ts": last_row["ts"],
            "source": last_row["source"],
        }

    db_constraints = [
        Constraint(
            id=c["id"],
            rule=c["rule"],
            ticker=c.get("ticker"),
            status="pending_confirmation",
            source="db",
            confirmed=False,
        )
        for c in store.read_active_constraints()
    ]
    run_constraints = list(inputs.new_constraints) + _parse_constraints_from_text(
        inputs.new_constraints_text
    )
    for c in run_constraints:
        c.status = "pending_confirmation"
        c.source = "run"
        c.confirmed = False

    constraints = db_constraints + run_constraints

    if inputs.xlsx_path:
        snapshot = parse_account_statement(inputs.xlsx_path)
        log_json(
            logger,
            "intake_parsed",
            run_id=run_id,
            positions=len(snapshot.positions),
            total_ars=str(snapshot.total_ars),
            mep_implied=str(snapshot.mep_implied),
            investor_alias=snapshot.investor_alias,
            constraints_pending=len(constraints),
            has_prev_snapshot=prev_snapshot is not None,
        )
        return {
            "snapshot": snapshot,
            "prev_snapshot": prev_snapshot,
            "degraded_mode": False,
            "staleness": None,
            "constraints": constraints,
            "technical_readings": state.get("technical_readings") or [],
            "info_gaps": state.get("info_gaps") or [],
        }

    # Modo degradado: sin .xlsx → último snapshot + staleness.
    if prev_snapshot is None or last_meta is None:
        raise MissingSnapshotError(
            "Modo degradado: no hay snapshot previo en el store de dominio. "
            "Corré primero con un .xlsx."
        )

    staleness = StalenessInfo(
        snapshot_id=last_meta["id"],
        snapshot_ts=last_meta["ts"],
        warning=_staleness_warning(last_meta["ts"], prev_snapshot.as_of),
        block_fine_quantities=True,
    )
    log_json(
        logger,
        "intake_degraded",
        run_id=run_id,
        snapshot_id=staleness.snapshot_id,
        snapshot_ts=staleness.snapshot_ts,
        warning=staleness.warning,
        constraints_pending=len(constraints),
        positions=len(prev_snapshot.positions),
    )
    return {
        "snapshot": prev_snapshot,
        "prev_snapshot": prev_snapshot,
        "degraded_mode": True,
        "staleness": staleness,
        "constraints": constraints,
        "technical_readings": state.get("technical_readings") or [],
        "info_gaps": state.get("info_gaps") or [],
    }


def _apply_echo_confirmation(
    constraints: list[Constraint],
    resume: dict[str, Any],
    *,
    store: PortfolioStore,
) -> list[Constraint]:
    """Aplica confirmación/revocación del echo-back; persiste altas y revokes (append-only)."""
    action = resume.get("action", "confirm_all")
    revoke_ids = {str(x) for x in resume.get("revoke_ids", [])}
    confirm_ids = resume.get("confirm_ids")
    confirm_set = {str(x) for x in confirm_ids} if confirm_ids is not None else None

    confirmed: list[Constraint] = []
    for c in constraints:
        cid = c.id or f"run:{c.ticker}:{c.rule}"
        should_revoke = action == "revoke" or cid in revoke_ids
        if action == "confirm" and confirm_set is not None and cid not in confirm_set:
            should_revoke = True

        if should_revoke:
            if c.source == "db" and c.rule:
                store.revoke_constraint(rule=c.rule, ticker=c.ticker)
            # No entra a constraints activas de la corrida.
            continue

        # Confirmada.
        if c.source == "run":
            row = store.write_constraint(rule=c.rule, ticker=c.ticker, status="active")
            confirmed.append(
                Constraint(
                    id=row["id"],
                    rule=c.rule,
                    ticker=c.ticker,
                    status="active",
                    source="echo",
                    confirmed=True,
                )
            )
        else:
            confirmed.append(
                Constraint(
                    id=c.id,
                    rule=c.rule,
                    ticker=c.ticker,
                    status="active",
                    source="echo",
                    confirmed=True,
                )
            )
    return confirmed


def orchestrator_node(state: PortfolioState, *, store: PortfolioStore) -> dict:
    """Orquestador F3: echo-back de restricciones (HITL) antes de analizar."""
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Orquestador: falta snapshot; el intake debió poblarlo")

    constraints = list(state.get("constraints") or [])
    inputs = state["inputs"]
    degraded = bool(state.get("degraded_mode", False))
    staleness = state.get("staleness")

    echo_payload = {
        "type": "constraint_echo_back",
        "run_id": run_id,
        "degraded_mode": degraded,
        "staleness": staleness.model_dump() if staleness else None,
        "constraints": [c.model_dump() for c in constraints],
        "prompt": (
            "Confirmá las restricciones antes de analizar. "
            "Resume con {action: confirm_all} o "
            "{action: confirm, revoke_ids: [...], confirm_ids: [...]}."
        ),
    }

    if constraints:
        if inputs.auto_confirm_constraints:
            resume: dict[str, Any] = {"action": "confirm_all"}
            log_json(logger, "orchestrator_echo_auto", run_id=run_id, n=len(constraints))
        else:
            log_json(
                logger,
                "orchestrator_echo_interrupt",
                run_id=run_id,
                n=len(constraints),
            )
            raw = interrupt(echo_payload)
            resume = raw if isinstance(raw, dict) else {"action": "confirm_all"}
        confirmed = _apply_echo_confirmation(constraints, resume, store=store)
    else:
        confirmed = []
        log_json(logger, "orchestrator_echo_empty", run_id=run_id)

    log_json(
        logger,
        "orchestrator_route",
        run_id=run_id,
        next="analista_cartera",
        degraded_mode=degraded,
        constraints_count=len(confirmed),
        block_fine_quantities=bool(staleness and staleness.block_fine_quantities),
        positions=len(snapshot.positions),
    )
    return {
        "constraints": confirmed,
        "degraded_mode": degraded,
        "staleness": staleness,
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


def _parse_mercado_json(raw: str) -> MercadoLLMOutput:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return MercadoLLMOutput.model_validate(json.loads(text))


def _invoke_mercado_llm(model: object, user_msg: str) -> MercadoLLMOutput:
    llm_out: MercadoLLMOutput | None = None
    try:
        structured = model.with_structured_output(MercadoLLMOutput)  # type: ignore[attr-defined]
        result = structured.invoke(
            [
                SystemMessage(content=MERCADO_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ]
        )
        if isinstance(result, MercadoLLMOutput):
            llm_out = result
        elif isinstance(result, dict):
            llm_out = MercadoLLMOutput.model_validate(result)
    except Exception as exc:  # noqa: BLE001
        log_json(logger, "mercado_structured_fallback", error=str(exc))

    if llm_out is None:
        raw = model.invoke(  # type: ignore[attr-defined]
            [
                SystemMessage(content=MERCADO_SYSTEM_PROMPT),
                HumanMessage(
                    content=user_msg + "\n\nRespondé ÚNICAMENTE un JSON con keys: "
                    "summary, instrument_notes, citations, narrative_delta."
                ),
            ]
        )
        content = raw.content if hasattr(raw, "content") else str(raw)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        llm_out = _parse_mercado_json(str(content))
    return llm_out


def _mercado_fallback_summary(
    *,
    as_of: str,
    mep_check: dict[str, Any],
    knowledge_ids: list[str],
    web_queries: list[str],
) -> MercadoLLMOutput:
    """Síntesis determinista sin LLM (tests / include_mercado stub path)."""
    warn = mep_check.get("mep_warning")
    summary = (
        f"Contexto de mercado al {as_of}: FX y quotes vía market-data; "
        f"retrieval knowledge={knowledge_ids}; web_queries={web_queries}."
    )
    if warn:
        summary += f" WARNING MEP: {warn}"
    citations = [
        MercadoCitation(source_id="market-data", note="FX y quotes de la corrida"),
        *[
            MercadoCitation(source_id=kid, note="documento knowledge recuperado")
            for kid in knowledge_ids[:5]
        ],
    ]
    return MercadoLLMOutput(
        summary=summary,
        instrument_notes=[],
        citations=citations,
        narrative_delta="",
    )


def analista_mercado_node(
    state: PortfolioState,
    *,
    chroma_dir: str | Path | None = None,
    skip_llm: bool = False,
) -> dict:
    """Analista de Mercado: market-data + web search nativa + RAG + verificación MEP."""
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Analista de Mercado: falta snapshot")

    persist = Path(chroma_dir) if chroma_dir else DEFAULT_CHROMA_DIR
    ensure_knowledge_ingested(persist_dir=persist)

    tickers = [p.ticker for p in snapshot.positions]
    fx = get_fx_rates()
    quotes = get_quotes(tickers)
    mep_market = mep_mid_from_fx(fx)
    mep_check = check_mep_divergence(snapshot.mep_implied, mep_market)

    today = date.today()
    as_of = today.isoformat()
    web_queries = [
        f"Mercado argentino acciones CEDEARS {as_of}",
        f"Dólar MEP CCL Argentina {as_of}",
    ]
    # Query extra por el ticker más pesado (concentración).
    if tickers:
        top = max(snapshot.positions, key=lambda p: p.total)
        web_queries.append(f"{top.ticker} cotización panel local {as_of}")

    web_blocks: list[str] = []
    for q in web_queries:
        payload = web_search(q, today=today)
        web_blocks.append(json.dumps(payload, ensure_ascii=False, indent=2))

    knowledge_hits = retrieve(
        "clustering drivers riesgo CEDEAR MEP gestión stops MACD",
        collection="knowledge",
        n_results=4,
        persist_dir=persist,
    )
    # Retrieval dirigido a informes previos (delta narrativo).
    report_hits = retrieve(
        f"informe cartera run restricciones diagnóstico {tickers[0] if tickers else ''}",
        collection="reports",
        n_results=3,
        persist_dir=persist,
    )
    knowledge_ids = [str(h["id"]) for h in knowledge_hits]
    report_ids = [str(h["id"]) for h in report_hits]

    diagnosis = state.get("diagnosis")
    diagnosis_line = (
        diagnosis.structural_diagnosis if diagnosis is not None else "(sin diagnóstico aún)"
    )
    fx_block = json.dumps(fx, ensure_ascii=False, indent=2)
    quotes_block = json.dumps(quotes, ensure_ascii=False, indent=2)
    mep_block = json.dumps(
        {k: str(v) if isinstance(v, Decimal) else v for k, v in mep_check.items()},
        ensure_ascii=False,
        indent=2,
    )
    user_msg = build_mercado_user_message(
        as_of_date=as_of,
        tickers=", ".join(tickers),
        fx_block=fx_block,
        quotes_block=quotes_block,
        mep_check_block=mep_block,
        web_block="\n\n".join(web_blocks),
        rag_knowledge_block=format_hits_as_untrusted_context(knowledge_hits),
        rag_reports_block=format_hits_as_untrusted_context(report_hits),
        diagnosis_one_liner=diagnosis_line,
    )

    if skip_llm:
        llm_out = _mercado_fallback_summary(
            as_of=as_of,
            mep_check=mep_check,
            knowledge_ids=knowledge_ids,
            web_queries=web_queries,
        )
    else:
        model = get_chat_model("mercado")
        try:
            llm_out = _invoke_mercado_llm(model, user_msg)
        except Exception as exc:  # noqa: BLE001 — degradar a síntesis determinista
            log_json(logger, "mercado_llm_failed", run_id=run_id, error=str(exc))
            llm_out = _mercado_fallback_summary(
                as_of=as_of,
                mep_check=mep_check,
                knowledge_ids=knowledge_ids,
                web_queries=web_queries,
            )

    instruments = [
        {
            "ticker": t,
            "quote": (quotes.get("quotes") or {}).get(t),
        }
        for t in tickers
    ]
    citations = [c.model_dump() for c in llm_out.citations]
    market_context = MarketContext(
        summary=llm_out.summary,
        instruments=instruments,
        fx_rates=fx,
        quotes=quotes,
        mep_implied=mep_check["mep_implied"],
        mep_market=mep_check["mep_market"],
        mep_divergence_pct=mep_check["mep_divergence_pct"],
        mep_warning=mep_check["mep_warning"],
        citations=citations,
        retrieved_knowledge_ids=knowledge_ids,
        retrieved_report_ids=report_ids,
        web_queries=web_queries,
        narrative_delta=llm_out.narrative_delta,
    )
    log_json(
        logger,
        "mercado_done",
        run_id=run_id,
        mep_warning=bool(market_context.mep_warning),
        knowledge_ids=knowledge_ids,
        report_ids=report_ids,
        web_queries=web_queries,
    )
    return {"market_context": market_context}


def _build_report_stub(state: PortfolioState) -> str:
    run_id = state.get("run_id", "")
    degraded = bool(state.get("degraded_mode", False))
    staleness = state.get("staleness")
    diagnosis = state.get("diagnosis")
    market_context = state.get("market_context")
    constraints = state.get("constraints") or []
    snapshot = state.get("snapshot")

    lines = [
        "# Informe stub (F4)",
        "",
        f"run_id: {run_id}",
        f"degraded_mode: {degraded}",
    ]
    if staleness is not None:
        lines.extend(
            [
                "",
                "## Staleness",
                staleness.warning,
                f"block_fine_quantities: {staleness.block_fine_quantities}",
                f"snapshot_id: {staleness.snapshot_id}",
            ]
        )
    if snapshot is not None:
        lines.extend(
            [
                "",
                "## Snapshot",
                f"positions: {len(snapshot.positions)}",
                f"total_ars: {snapshot.total_ars}",
                f"mep_implied: {snapshot.mep_implied}",
            ]
        )
    if constraints:
        lines.append("")
        lines.append("## Restricciones confirmadas")
        for c in constraints:
            lines.append(f"- [{c.status}] {c.rule}" + (f" ({c.ticker})" if c.ticker else ""))
    if diagnosis is not None:
        lines.extend(
            [
                "",
                "## Diagnóstico (borrador)",
                diagnosis.structural_diagnosis,
            ]
        )
    if market_context is not None:
        lines.extend(
            [
                "",
                "## Contexto de mercado",
                market_context.summary,
            ]
        )
        if market_context.mep_warning:
            lines.extend(["", "### Warning MEP", market_context.mep_warning])
        if market_context.citations:
            lines.append("")
            lines.append("### Citas")
            for c in market_context.citations:
                lines.append(f"- [{c.get('source_id')}] {c.get('note')}")
    plan = state.get("plan")
    if plan is not None:
        lines.extend(["", "## Plan de rebalanceo (F5)"])
        lines.append(plan.reasoning or plan.notes or "")
        for a in plan.actions:
            lines.append(
                f"- {a.ticker}: {a.action}"
                + (f" qty={a.quantity}" if a.quantity is not None else "")
                + (f" stop={a.stop_level}" if a.stop_level is not None else "")
            )
        if plan.ml_inputs:
            lines.append("")
            lines.append("### Insumos predict_trend")
            for m in plan.ml_inputs:
                lines.append(f"- {m.ticker}: {m.note}")
    validation = state.get("validation")
    if validation is not None:
        lines.extend(
            [
                "",
                "## Validación",
                f"approved={validation.approved} attempt={validation.attempt}",
            ]
        )
        for fb in validation.feedback:
            lines.append(f"- {fb}")
    gaps = state.get("info_gaps") or []
    if gaps:
        lines.append("")
        lines.append("## Info gaps")
        for g in gaps:
            detail = g.detail if hasattr(g, "detail") else g.get("detail")
            ticker = g.ticker if hasattr(g, "ticker") else g.get("ticker")
            lines.append(f"- {ticker}: {detail}")
    lines.extend(
        [
            "",
            "---",
            "Descargo: este sistema no ejecuta órdenes ni constituye asesoramiento financiero.",
        ]
    )
    return "\n".join(lines)


def persist_node(
    state: PortfolioState,
    *,
    store: PortfolioStore,
    chroma_dir: str | Path | None = None,
) -> dict:
    """Persistencia: snapshot (si .xlsx) + informe + ingesta del informe a Chroma."""
    run_id = state.get("run_id", "")
    inputs = state["inputs"]
    degraded = bool(state.get("degraded_mode", False))
    snapshot = state.get("snapshot")
    report_md = _build_report_stub(state)
    persist = Path(chroma_dir) if chroma_dir else DEFAULT_CHROMA_DIR

    snapshot_meta = None
    if not degraded and inputs.xlsx_path and snapshot is not None:
        snapshot_meta = store.write_snapshot(
            snapshot_to_store_dict(snapshot),
            source=inputs.xlsx_path,
        )
        log_json(
            logger,
            "persist_snapshot",
            run_id=run_id,
            snapshot_id=snapshot_meta["id"],
            source=snapshot_meta["source"],
        )
    else:
        log_json(
            logger,
            "persist_snapshot_skipped",
            run_id=run_id,
            reason="degraded_mode" if degraded else "no_xlsx_or_snapshot",
        )

    report_meta = store.write_report(run_id=run_id, content_md=report_md)
    ingest_meta = ingest_report(
        report_id=report_meta["id"],
        run_id=run_id,
        content_md=report_md,
        persist_dir=persist,
    )
    log_json(
        logger,
        "persist_report",
        run_id=run_id,
        report_id=report_meta["id"],
        snapshot_written=snapshot_meta is not None,
        chroma_indexed=ingest_meta["id"],
    )
    return {"report": report_md}
