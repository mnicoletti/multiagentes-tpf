"""Nodos F5: técnico, planificador, validator, gaps HITL."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from portfoliosentinel.agents.planificador import PlannerLLMOutput
from portfoliosentinel.agents.prompts.planificador import (
    PLANIFICADOR_SYSTEM_PROMPT,
    build_planificador_user_message,
)
from portfoliosentinel.agents.prompts.tecnico import (
    TECNICO_SYSTEM_PROMPT,
    build_tecnico_user_message,
)
from portfoliosentinel.agents.tecnico import TecnicoLLMOutput
from portfoliosentinel.config.models import get_chat_model
from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR
from portfoliosentinel.graph.f5_logic import (
    build_deterministic_plan,
    enrich_restricted_mitigations,
    stub_technical_readings,
)
from portfoliosentinel.graph.logging_utils import get_node_logger, log_json
from portfoliosentinel.graph.state import (
    InfoGap,
    PlanAction,
    PortfolioState,
    RebalancePlan,
    TechnicalReading,
    ValidationResult,
)
from portfoliosentinel.rag.ingest import ensure_knowledge_ingested
from portfoliosentinel.rag.retriever import format_hits_as_untrusted_context, retrieve
from portfoliosentinel.tools.calc import compute_rebalance, trades_from_plan_actions
from portfoliosentinel.tools.guardrails import max_validator_retries, validate_plan

logger = get_node_logger("portfoliosentinel.graph.nodes_f5")


def _parse_json_model(raw: str, model_cls: type):
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return model_cls.model_validate(json.loads(text))


def _image_content_block(path: str) -> dict[str, Any]:
    p = Path(path)
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    mime, _ = mimetypes.guess_type(p.name)
    if not mime:
        mime = "image/png"
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
    }


def analista_tecnico_node(
    state: PortfolioState,
    *,
    chroma_dir: str | Path | None = None,
    skip_llm: bool = False,
) -> dict:
    """Analista Técnico multimodal: propósito de cada imagen = input del usuario."""
    run_id = state.get("run_id", "")
    inputs = state["inputs"]
    image_paths = list(inputs.image_paths or [])
    purposes = dict(inputs.image_purposes or {})

    # Resume de gaps puede traer paths extras en pending_gap_resume
    pending = state.get("pending_gap_resume") or {}
    extra_paths = list(pending.get("image_paths") or [])
    extra_purposes = dict(pending.get("image_purposes") or {})
    resume_stops_raw = pending.get("stop_levels") or {}
    resume_stops = {str(k).upper(): Decimal(str(v)) for k, v in resume_stops_raw.items()}

    all_paths = list(dict.fromkeys([*image_paths, *extra_paths]))
    all_purposes = {**purposes, **extra_purposes}

    if not all_paths:
        log_json(logger, "tecnico_skip_no_images", run_id=run_id)
        return {"technical_readings": state.get("technical_readings") or []}

    if skip_llm:
        readings = stub_technical_readings(all_paths, all_purposes, resume_stop_levels=resume_stops)
        log_json(
            logger,
            "tecnico_stub_done",
            run_id=run_id,
            n=len(readings),
            purposes=[r.purpose for r in readings],
        )
        return {"technical_readings": readings, "pending_gap_resume": None}

    persist = Path(chroma_dir) if chroma_dir else DEFAULT_CHROMA_DIR
    ensure_knowledge_ingested(persist_dir=persist)
    hits = retrieve(
        "MACD RSI medias móviles gestión stops metodología",
        collection="knowledge",
        n_results=3,
        persist_dir=persist,
    )
    rag_block = format_hits_as_untrusted_context(hits)
    specs = [
        {
            "path": p,
            "purpose": all_purposes.get(p) or all_purposes.get(Path(p).name) or "unspecified",
            "ticker": "",
        }
        for p in all_paths
    ]
    user_text = build_tecnico_user_message(
        image_specs=specs,
        rag_block=rag_block,
        user_notes=inputs.user_notes,
    )

    content: list[Any] = [{"type": "text", "text": user_text}]
    for p in all_paths:
        if Path(p).is_file():
            content.append(_image_content_block(p))
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"[dato no confiable — imagen] path={p} "
                        f"purpose={all_purposes.get(p, 'unspecified')}"
                    ),
                }
            )

    model = get_chat_model("tecnico")
    llm_out: TecnicoLLMOutput | None = None
    try:
        structured = model.with_structured_output(TecnicoLLMOutput)  # type: ignore[attr-defined]
        result = structured.invoke(
            [
                SystemMessage(content=TECNICO_SYSTEM_PROMPT),
                HumanMessage(content=content),
            ]
        )
        if isinstance(result, TecnicoLLMOutput):
            llm_out = result
        elif isinstance(result, dict):
            llm_out = TecnicoLLMOutput.model_validate(result)
    except Exception as exc:  # noqa: BLE001
        log_json(logger, "tecnico_structured_fallback", error=str(exc))

    if llm_out is None:
        try:
            raw = model.invoke(  # type: ignore[attr-defined]
                [
                    SystemMessage(content=TECNICO_SYSTEM_PROMPT),
                    HumanMessage(content=content),
                ]
            )
            raw_content = raw.content if hasattr(raw, "content") else str(raw)
            if isinstance(raw_content, list):
                raw_content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in raw_content
                )
            llm_out = _parse_json_model(str(raw_content), TecnicoLLMOutput)
        except Exception as exc:  # noqa: BLE001
            log_json(logger, "tecnico_llm_failed", run_id=run_id, error=str(exc))
            readings = stub_technical_readings(
                all_paths, all_purposes, resume_stop_levels=resume_stops
            )
            return {"technical_readings": readings, "pending_gap_resume": None}

    readings: list[TechnicalReading] = []
    for i, r in enumerate(llm_out.readings):
        path = all_paths[i] if i < len(all_paths) else all_paths[-1]
        purpose = all_purposes.get(path) or all_purposes.get(Path(path).name) or "unspecified"
        stop = r.stop_level
        ticker_u = (r.ticker or "").upper() or None
        # Screening no exige stop (el gap lo pide el planificador solo si hace falta).
        is_screening = "screening" in purpose.lower()
        # Hard rule: if model invents stop without visibility flag, drop it —
        # salvo HITL resume que aportó el nivel para ese ticker.
        if (
            stop is not None
            and not r.stop_visible_in_image
            and not (ticker_u and ticker_u in resume_stops)
        ):
            stop = None
            r.needs_stop_level = True
        if ticker_u and ticker_u in resume_stops:
            stop = resume_stops[ticker_u]
            r.needs_stop_level = False
        needs_stop = False if is_screening else bool(r.needs_stop_level and stop is None)
        readings.append(
            TechnicalReading(
                image_path=path,
                purpose=purpose,
                ticker=ticker_u,
                summary=r.summary,
                trend=r.trend,
                indicators=r.indicators,
                verdict=r.verdict,
                needs_stop_level=needs_stop,
                stop_level=stop,
            )
        )

    # HITL: asegurar lectura con stop por cada ticker confirmado (aunque el LLM
    # no lo haya atado a una imagen).
    present = {(r.ticker or "").upper() for r in readings if r.ticker}
    updated: list[TechnicalReading] = []
    for r in readings:
        t = (r.ticker or "").upper()
        if t and t in resume_stops:
            updated.append(
                r.model_copy(
                    update={
                        "stop_level": resume_stops[t],
                        "needs_stop_level": False,
                    }
                )
            )
        else:
            updated.append(r)
    readings = updated
    for ticker, level in resume_stops.items():
        if ticker not in present:
            readings.append(
                TechnicalReading(
                    image_path="hitl://resume-stop",
                    purpose="stop_chart",
                    ticker=ticker,
                    summary=f"Stop confirmado por usuario (HITL resume): {level}",
                    trend=None,
                    indicators={"source": "hitl_resume"},
                    verdict="stop_confirmado_hitl",
                    needs_stop_level=False,
                    stop_level=level,
                )
            )

    log_json(logger, "tecnico_done", run_id=run_id, n=len(readings))
    # pending_gap_resume lo consume el planificador (no borrar acá).
    return {"technical_readings": readings}


def _snapshot_block(state: PortfolioState) -> str:
    snap = state.get("snapshot")
    if snap is None:
        return "(sin snapshot)"
    lines = [
        f"total_ars={snap.total_ars} total_usd={snap.total_usd} mep={snap.mep_implied}",
    ]
    for p in snap.positions:
        lines.append(
            f"- {p.ticker} [{p.asset_class}] qty={p.quantity} price={p.price} total={p.total}"
        )
    return "\n".join(lines)


def planificador_node(state: PortfolioState, *, skip_llm: bool = False) -> dict:
    """Planificador: combina insumos; gaps si falta stop; cita predict_trend."""
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Planificador: falta snapshot")

    inputs = state["inputs"]
    constraints = list(state.get("constraints") or [])
    diagnosis = state.get("diagnosis")
    market = state.get("market_context")
    technical = list(state.get("technical_readings") or [])
    validation = state.get("validation")
    feedback = list(validation.feedback) if validation and not validation.approved else []

    # Flag de test: inputs.user_notes puede pedir force_illegal_sell=TICKER
    force_illegal = None
    if inputs.user_notes and "force_illegal_sell=" in inputs.user_notes:
        m = re.search(r"force_illegal_sell=([A-Za-z0-9.]+)", inputs.user_notes)
        if m:
            force_illegal = m.group(1).upper()

    if skip_llm:
        plan, gaps = build_deterministic_plan(
            snapshot=snapshot,
            constraints=constraints,
            diagnosis=diagnosis,
            technical_readings=technical,
            capital_new_ars=inputs.capital_new_ars,
            validation_feedback=feedback,
            force_illegal_sell=force_illegal,
        )
        log_json(
            logger,
            "planificador_stub_done",
            run_id=run_id,
            actions=[a.action + ":" + a.ticker for a in plan.actions],
            gaps=[g.ticker for g in gaps],
            ml_cited=len(plan.ml_inputs),
        )
        return {"plan": plan, "info_gaps": gaps}

    # Camino LLM
    from portfoliosentinel.graph.f5_logic import collect_ml_signals

    ml_inputs = collect_ml_signals([p.ticker for p in snapshot.positions[:4]])
    ml_block = "\n".join(f"- {m.ticker}: {m.note}" for m in ml_inputs)
    tech_block = (
        "\n".join(
            f"- [{r.purpose}] {r.ticker or '?'}: {r.summary} "
            f"needs_stop={r.needs_stop_level} stop={r.stop_level}"
            for r in technical
        )
        or "(sin lecturas técnicas)"
    )
    constraints_block = (
        "\n".join(f"- {c.rule}" + (f" ({c.ticker})" if c.ticker else "") for c in constraints)
        or "(ninguna)"
    )
    diagnosis_block = diagnosis.structural_diagnosis if diagnosis else "(sin diagnóstico)"
    market_block = market.summary if market else "(sin mercado)"

    # Calc previa vacía — se completa tras el plan
    user_msg = build_planificador_user_message(
        snapshot_block=_snapshot_block(state),
        constraints_block=constraints_block,
        diagnosis_block=diagnosis_block,
        market_block=market_block,
        technical_block=tech_block,
        ml_block=ml_block,
        calc_block="(se calculará tras armar acciones)",
        capital_new=str(inputs.capital_new_ars or 0),
        validation_feedback="\n".join(feedback),
        user_notes=inputs.user_notes,
    )

    model = get_chat_model("planificador")
    llm_out: PlannerLLMOutput | None = None
    try:
        structured = model.with_structured_output(PlannerLLMOutput)  # type: ignore[attr-defined]
        result = structured.invoke(
            [
                SystemMessage(content=PLANIFICADOR_SYSTEM_PROMPT),
                HumanMessage(content=user_msg),
            ]
        )
        if isinstance(result, PlannerLLMOutput):
            llm_out = result
        elif isinstance(result, dict):
            llm_out = PlannerLLMOutput.model_validate(result)
    except Exception as exc:  # noqa: BLE001
        log_json(logger, "planificador_structured_fallback", error=str(exc))

    if llm_out is None:
        try:
            raw = model.invoke(  # type: ignore[attr-defined]
                [
                    SystemMessage(content=PLANIFICADOR_SYSTEM_PROMPT),
                    HumanMessage(content=user_msg + "\n\nRespondé ÚNICAMENTE JSON válido."),
                ]
            )
            content = raw.content if hasattr(raw, "content") else str(raw)
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                )
            llm_out = _parse_json_model(str(content), PlannerLLMOutput)
        except Exception as exc:  # noqa: BLE001
            log_json(logger, "planificador_llm_failed", run_id=run_id, error=str(exc))
            plan, gaps = build_deterministic_plan(
                snapshot=snapshot,
                constraints=constraints,
                diagnosis=diagnosis,
                technical_readings=technical,
                capital_new_ars=inputs.capital_new_ars,
                validation_feedback=feedback,
                force_illegal_sell=force_illegal,
            )
            return {"plan": plan, "info_gaps": gaps}

    actions = [
        PlanAction(
            ticker=a.ticker.upper(),
            action=a.action,
            quantity=a.quantity,
            pct_of_position=a.pct_of_position,
            rationale=a.rationale,
            stop_level=a.stop_level,
            ml_signal_cited=a.ml_signal_cited,
            risk_notes=list(a.risk_notes),
            mitigations=list(a.mitigations),
        )
        for a in llm_out.actions
    ]

    # Stops ya resueltos: lecturas técnicas + HITL resume (si aún está pending).
    stops_by_ticker: dict[str, Decimal] = {
        r.ticker.upper(): r.stop_level for r in technical if r.ticker and r.stop_level is not None
    }
    pending = state.get("pending_gap_resume") or {}
    for k, v in (pending.get("stop_levels") or {}).items():
        stops_by_ticker.setdefault(str(k).upper(), Decimal(str(v)))

    for a in actions:
        if a.ticker.upper() in stops_by_ticker and a.stop_level is None:
            a.stop_level = stops_by_ticker[a.ticker.upper()]

    # SPEC GC-2: restringido → riesgo + mitigaciones (determinista; no depende del LLM).
    actions = enrich_restricted_mitigations(
        actions, snapshot=snapshot, constraints=constraints
    )

    # Hard post-process: nunca inventar stops; gap solo si hace falta y no hay HITL.
    needs = {
        r.ticker.upper()
        for r in technical
        if r.ticker
        and r.needs_stop_level
        and r.stop_level is None
        and "screening" not in (r.purpose or "").lower()
    }
    needs -= set(stops_by_ticker.keys())

    gaps: list[InfoGap] = []
    for a in actions:
        if a.ticker.upper() in needs and a.stop_level is not None:
            # Drop invented stop
            a.stop_level = None
        if a.ticker.upper() in needs and a.stop_level is None:
            gaps.append(
                InfoGap(
                    kind="missing_stop_chart",
                    ticker=a.ticker.upper(),
                    detail=(
                        f"Falta gráfico ampliado para fijar stop de {a.ticker}. "
                        "Prohibido inventar el nivel."
                    ),
                )
            )
    for g in llm_out.info_gaps:
        t = g.ticker.upper()
        # Solo aceptar gaps LLM que el post-proceso determinista también exige
        # (evita que el modelo invente gaps MELI/SPY/screening en loop).
        if t not in needs:
            continue
        if t in stops_by_ticker:
            continue
        gaps.append(InfoGap(kind=g.kind, ticker=t, detail=g.detail))
    # dedupe gaps by ticker
    seen: set[str] = set()
    uniq_gaps: list[InfoGap] = []
    for g in gaps:
        key = f"{g.kind}:{g.ticker}"
        if key in seen:
            continue
        if g.ticker.upper() in stops_by_ticker:
            continue
        seen.add(key)
        uniq_gaps.append(g)

    trades = trades_from_plan_actions(actions)
    calc = compute_rebalance(
        snapshot,
        trades,
        capital_new_ars=inputs.capital_new_ars,
        clusters=list(diagnosis.clusters) if diagnosis else None,
    )

    reasoning = llm_out.reasoning
    if "predict_trend" not in reasoning and ml_inputs:
        reasoning += " Insumos ML (predict_trend, no decisión): " + "; ".join(
            m.note for m in ml_inputs
        )

    plan = RebalancePlan(
        actions=actions,
        capital_allocation=list(llm_out.capital_allocation),
        calculator_result=calc.model_dump(mode="json"),
        ml_inputs=ml_inputs,
        notes=llm_out.notes,
        reasoning=reasoning,
    )
    log_json(
        logger,
        "planificador_done",
        run_id=run_id,
        n_actions=len(actions),
        gaps=[g.ticker for g in uniq_gaps],
    )
    return {
        "plan": plan,
        "info_gaps": uniq_gaps,
        "pending_gap_resume": None,
    }


def validator_node(state: PortfolioState) -> dict:
    """Validator determinista de hard constraints (YAML + código)."""
    run_id = state.get("run_id", "")
    plan = state.get("plan")
    snapshot = state.get("snapshot")
    if plan is None or snapshot is None:
        raise ValueError("Validator: faltan plan o snapshot")

    prev = state.get("validation")
    attempt = (prev.attempt if prev else 0) + 1
    result = validate_plan(
        plan,
        snapshot=snapshot,
        constraints=list(state.get("constraints") or []),
        attempt=attempt,
    )
    traces = list(state.get("validator_traces") or [])
    traces.append(
        {
            "attempt": result.attempt,
            "approved": result.approved,
            "feedback": list(result.feedback),
            "violations": [v.model_dump() for v in result.violations],
        }
    )
    log_json(
        logger,
        "validator_done",
        run_id=run_id,
        attempt=attempt,
        approved=result.approved,
        n_violations=len(result.violations),
        feedback=result.feedback,
    )
    return {"validation": result, "validator_traces": traces}


def route_after_validator(
    state: PortfolioState,
) -> Literal["planificador", "validation_escalate", "gaps_interrupt", "redactor", "persist"]:
    """Tras plan aprobado sin gaps → redactor (F6). `persist` queda por compat."""
    validation = state.get("validation")
    if validation is None:
        return "redactor"
    max_retries = max_validator_retries()
    if not validation.approved:
        # attempt 1 = primer plan; retries permiten hasta max_retries replanes
        if validation.attempt > max_retries:
            return "validation_escalate"
        return "planificador"
    gaps = state.get("info_gaps") or []
    if gaps:
        return "gaps_interrupt"
    return "redactor"


def route_after_gaps_interrupt(
    state: PortfolioState,
) -> Literal["analista_tecnico", "planificador"]:
    """Tras HITL: si hay imágenes nuevas → técnico; si solo stop_levels → planificador.

    Evita re-correr visión multimodal (caro) cuando el usuario solo confirma niveles.
    """
    pending = state.get("pending_gap_resume") or {}
    new_images = [p for p in (pending.get("image_paths") or []) if p]
    if new_images:
        return "analista_tecnico"
    return "planificador"


def validation_escalate_node(state: PortfolioState) -> dict:
    """Tras max reintentos del validator → interrupt HITL."""
    run_id = state.get("run_id", "")
    validation = state.get("validation")
    payload = {
        "type": "validation_escalate",
        "run_id": run_id,
        "attempt": validation.attempt if validation else None,
        "feedback": list(validation.feedback) if validation else [],
        "prompt": (
            "El plan violó hard constraints tras reintentos. "
            "Resume con {action: accept_risk} o {action: provide_guidance, guidance: '...'}."
        ),
    }
    log_json(logger, "validation_escalate_interrupt", run_id=run_id)
    raw = interrupt(payload)
    resume = raw if isinstance(raw, dict) else {"action": "accept_risk"}
    log_json(logger, "validation_escalate_resumed", run_id=run_id, resume=resume)
    # Marcamos approved forzado solo si el usuario acepta riesgo explícitamente;
    # si no, dejamos el plan tal cual y seguimos a persist con validation rechazada.
    if resume.get("action") == "accept_risk" and validation is not None:
        forced = ValidationResult(
            approved=True,
            feedback=list(validation.feedback) + ["HITL accept_risk"],
            violations=list(validation.violations),
            attempt=validation.attempt,
        )
        return {"validation": forced}
    return {}


def gaps_interrupt_node(state: PortfolioState) -> dict:
    """interrupt() por info_gaps (falta gráfico para stop)."""
    run_id = state.get("run_id", "")
    gaps = [
        g.model_dump() if hasattr(g, "model_dump") else g for g in (state.get("info_gaps") or [])
    ]
    payload = {
        "type": "info_gaps",
        "run_id": run_id,
        "gaps": gaps,
        "prompt": (
            "Faltan gráficos/niveles para completar stops. "
            "Resume con {image_paths: [...], image_purposes: {...}, stop_levels: {TICKER: n}}."
        ),
    }
    log_json(logger, "gaps_interrupt", run_id=run_id, gaps=gaps)
    raw = interrupt(payload)
    resume = raw if isinstance(raw, dict) else {}
    log_json(logger, "gaps_resumed", run_id=run_id, keys=list(resume.keys()))

    # Merge nuevas imágenes en inputs
    inputs = state["inputs"]
    new_paths = list(resume.get("image_paths") or [])
    new_purposes = dict(resume.get("image_purposes") or {})
    merged_paths = list(dict.fromkeys([*(inputs.image_paths or []), *new_paths]))
    merged_purposes = {**(inputs.image_purposes or {}), **new_purposes}
    updated_inputs = inputs.model_copy(
        update={"image_paths": merged_paths, "image_purposes": merged_purposes}
    )
    return {
        "inputs": updated_inputs,
        "pending_gap_resume": resume,
        "info_gaps": [],  # se regeneran en el replan si aún faltan
    }
