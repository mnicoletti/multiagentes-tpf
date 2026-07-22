"""Nodos F6: Redactor + linter de informe + ruteo de rechazo."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from portfoliosentinel.agents.prompts.redactor import (
    REDACTOR_SYSTEM_PROMPT,
    build_redactor_user_message,
)
from portfoliosentinel.config.models import get_chat_model
from portfoliosentinel.graph.logging_utils import get_node_logger, log_json
from portfoliosentinel.graph.message_text import message_text
from portfoliosentinel.graph.report_builder import build_report_from_state
from portfoliosentinel.graph.state import PortfolioState
from portfoliosentinel.tools.guardrails import lint_report, max_report_linter_retries

logger = get_node_logger("portfoliosentinel.graph.nodes_f6")

# Marcadores mínimos del linter (SPEC §6.3 / guardrails.yaml). Si el LLM
# no los trae, no quemamos 3 reintentos: caemos al builder determinista.
_STRUCTURE_MARKERS = (
    "## 1. Encabezado",
    "## 7. Plan de acción consolidado",
    "no constituye asesoramiento financiero",
)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    fence = re.search(r"```(?:markdown|md)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _looks_structured(report_md: str) -> bool:
    return all(marker in report_md for marker in _STRUCTURE_MARKERS)


def _invoke_redactor_llm(model: object, user_msg: str) -> str:
    raw = model.invoke(  # type: ignore[attr-defined]
        [
            SystemMessage(content=REDACTOR_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ]
    )
    return _strip_fences(message_text(raw))


def _snapshot_block(state: PortfolioState) -> str:
    snapshot = state.get("snapshot")
    if snapshot is None:
        return "(sin snapshot)"
    lines = [
        f"alias={snapshot.investor_alias}",
        f"total_ars={snapshot.total_ars}",
        f"total_usd={snapshot.total_usd}",
        f"mep_implied={snapshot.mep_implied}",
        "positions:",
    ]
    for p in snapshot.positions:
        lines.append(
            f"- {p.ticker} [{p.asset_class}] qty={p.quantity} price={p.price} total={p.total}"
        )
    return "\n".join(lines)


def redactor_node(state: PortfolioState, *, skip_llm: bool = False) -> dict:
    """Redactor: informe §6.3. Ante feedback del linter, reintenta con el motivo puntual."""
    run_id = state.get("run_id", "")
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Redactor: falta snapshot")

    inputs = state["inputs"]
    feedback = list(state.get("report_linter_feedback") or [])
    diagnosis = state.get("diagnosis")
    market = state.get("market_context")
    plan = state.get("plan")
    technical = list(state.get("technical_readings") or [])
    constraints = list(state.get("constraints") or [])
    staleness = state.get("staleness")

    constraints_block = (
        "\n".join(
            f"- [{c.status}] {c.rule}" + (f" ({c.ticker})" if c.ticker else "") for c in constraints
        )
        or "(ninguna)"
    )
    diagnosis_block = (
        diagnosis.model_dump_json(indent=2) if diagnosis is not None else "(sin diagnóstico)"
    )
    market_block = (
        json.dumps(
            {
                "summary": market.summary,
                "mep_warning": market.mep_warning,
                "citations": market.citations,
            },
            ensure_ascii=False,
            indent=2,
        )
        if market is not None
        else "(sin mercado)"
    )
    technical_block = json.dumps(
        [r.model_dump(mode="json") for r in technical],
        ensure_ascii=False,
        indent=2,
    )
    plan_block = plan.model_dump_json(indent=2) if plan is not None else "(sin plan)"
    degraded_block = ""
    if state.get("degraded_mode") and staleness is not None:
        degraded_block = staleness.warning

    if skip_llm:
        report_md = build_report_from_state(state)
        log_json(logger, "redactor_stub_done", run_id=run_id, chars=len(report_md))
        return {"report": report_md, "report_linter_feedback": []}

    llm_attempt = len(state.get("report_lint_traces") or []) + 1
    log_json(
        logger,
        "redactor_start",
        run_id=run_id,
        llm_attempt=llm_attempt,
        had_feedback=bool(feedback),
        feedback_n=len(feedback),
    )

    user_msg = build_redactor_user_message(
        snapshot_block=_snapshot_block(state),
        constraints_block=constraints_block,
        diagnosis_block=diagnosis_block,
        market_block=market_block,
        technical_block=technical_block,
        plan_block=plan_block,
        capital_new=str(inputs.capital_new_ars) if inputs.capital_new_ars is not None else "0",
        degraded_block=degraded_block,
        linter_feedback="\n".join(feedback),
    )
    model = get_chat_model("redactor")
    used_fallback = False
    try:
        report_md = _invoke_redactor_llm(model, user_msg)
    except Exception as exc:  # noqa: BLE001 — degradar a informe determinista
        log_json(logger, "redactor_llm_failed", run_id=run_id, error=str(exc))
        report_md = build_report_from_state(state)
        used_fallback = True

    if not used_fallback and not _looks_structured(report_md):
        # Evita el loop caro linter→redactor×3 cuando el LLM ignora §6.3.
        log_json(
            logger,
            "redactor_structure_fallback",
            run_id=run_id,
            llm_chars=len(report_md),
            preview=report_md[:160].replace("\n", " "),
        )
        report_md = build_report_from_state(state)
        used_fallback = True

    log_json(
        logger,
        "redactor_done",
        run_id=run_id,
        chars=len(report_md),
        had_feedback=bool(feedback),
        llm_attempt=llm_attempt,
        used_fallback=used_fallback,
    )
    return {"report": report_md, "report_linter_feedback": []}


def report_linter_node(state: PortfolioState) -> dict:
    """Linter determinista post-Redactor. Si rechaza, el informe NO sale."""
    run_id = state.get("run_id", "")
    report_md = state.get("report") or ""
    snapshot = state.get("snapshot")
    if snapshot is None:
        raise ValueError("Report linter: falta snapshot")

    prev = state.get("report_lint")
    attempt = (prev.attempt if prev else 0) + 1
    result = lint_report(
        report_md,
        snapshot=snapshot,
        constraints=list(state.get("constraints") or []),
        attempt=attempt,
    )
    traces = list(state.get("report_lint_traces") or [])
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
        "report_linter_done",
        run_id=run_id,
        attempt=attempt,
        approved=result.approved,
        n_violations=len(result.violations),
        feedback=result.feedback,
    )
    out: dict[str, Any] = {
        "report_lint": result,
        "report_lint_traces": traces,
    }
    if not result.approved:
        # El informe no sale: se limpia hasta que el Redactor produzca uno válido.
        out["report"] = None
        out["report_linter_feedback"] = list(result.feedback)
    else:
        out["report_linter_feedback"] = []
    return out


def route_after_report_linter(
    state: PortfolioState,
) -> Literal["redactor", "persist", "report_lint_fail"]:
    """Rechazo → Redactor; aprobado → persist; agotados reintentos → sin informe."""
    lint = state.get("report_lint")
    if lint is None:
        return "persist"
    if lint.approved:
        return "persist"
    if lint.attempt > max_report_linter_retries():
        return "report_lint_fail"
    return "redactor"


def report_lint_fail_node(state: PortfolioState) -> dict:
    """Tras max reintentos: el informe NO sale (report=None); se sigue a persist de snapshot."""
    run_id = state.get("run_id", "")
    lint = state.get("report_lint")
    log_json(
        logger,
        "report_lint_fail",
        run_id=run_id,
        attempt=lint.attempt if lint else None,
        feedback=list(lint.feedback) if lint else [],
    )
    return {"report": None}
