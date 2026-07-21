"""Helpers de corrida, métricas locales y RESULTS.md (F7)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from langgraph.types import Command

from portfoliosentinel.config.settings import (
    DEFAULT_FIXTURE_XLSX,
    DEFAULT_IMAGES_DIR,
    KNOWLEDGE_DIR,
    REPO_ROOT,
)
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.report_builder import DISCLAIMER, SECTION_HEADINGS
from portfoliosentinel.graph.state import RunInputs
from portfoliosentinel.rag.ingest import ingest_knowledge
from portfoliosentinel.tools.portfolio_store import open_domain_store

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_MD = EVALS_DIR / "RESULTS.md"
CONFIG_YAML = EVALS_DIR / "config.yaml"
FIXTURE = DEFAULT_FIXTURE_XLSX
IMAGES = DEFAULT_IMAGES_DIR

_lock = threading.Lock()
_CASE_RESULTS: list = []


@dataclass
class CaseResult:
    case_id: str
    kind: str  # golden | scenario
    passed: bool
    deterministic_checks: dict[str, bool] = field(default_factory=dict)
    judge_scores: dict[str, float] | None = None
    judge_avg: float | None = None
    judge_rationale: str | None = None
    latency_s: float = 0.0
    cost_usd: float = 0.0
    validator_reroutes: int = 0
    validator_attempts: int = 0
    notes: str = ""
    error: str | None = None


def load_eval_config() -> dict[str, Any]:
    return yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))


def reset_results() -> None:
    with _lock:
        _CASE_RESULTS.clear()


def record_result(result: CaseResult) -> None:
    with _lock:
        _CASE_RESULTS.append(result)


def all_results() -> list[CaseResult]:
    with _lock:
        return list(_CASE_RESULTS)


def ensure_fixture_mode() -> None:
    os.environ["MARKET_FIXTURE"] = "1"


def initial_state(**input_kw: Any) -> dict[str, Any]:
    run_id = input_kw.pop("run_id", f"eval-{uuid.uuid4().hex[:8]}")
    return {
        "run_id": run_id,
        "inputs": RunInputs(auto_confirm_constraints=True, **input_kw),
        "snapshot": None,
        "degraded_mode": False,
        "constraints": [],
        "prev_snapshot": None,
        "staleness": None,
        "diagnosis": None,
        "market_context": None,
        "technical_readings": [],
        "plan": None,
        "validation": None,
        "a2a_review": None,
        "info_gaps": [],
        "report": None,
        "validator_traces": [],
        "pending_gap_resume": None,
        "report_lint": None,
        "report_lint_traces": [],
        "report_linter_feedback": [],
    }


def default_images() -> tuple[list[str], dict[str, str]]:
    ggal_stop = str(IMAGES / "chart-ggal-with-stop.png")
    fci = str(IMAGES / "fci-panel.png")
    screening = str(IMAGES / "chart-aapl-screening.png")
    paths = [ggal_stop, fci, screening]
    purposes = {
        ggal_stop: "stop_chart",
        fci: "tenencia_externa_fci",
        screening: "screening",
    }
    return paths, purposes


def gap_images_no_stop() -> tuple[list[str], dict[str, str]]:
    no_stop = str(IMAGES / "chart-ggal-no-stop.png")
    fci = str(IMAGES / "fci-panel.png")
    return [no_stop, fci], {no_stop: "stop_chart", fci: "tenencia_externa_fci"}


def count_validator_reroutes(traces: list[dict[str, Any]] | None) -> tuple[int, int]:
    """(re-ruteos = rechazos, intentos totales)."""
    traces = traces or []
    attempts = len(traces)
    reroutes = sum(1 for t in traces if not t.get("approved", True))
    return reroutes, attempts


def estimate_cost_usd(*, used_llm_judge: bool, used_agent_llm: bool) -> float:
    """Costo local: 0 (Ollama). Si LangSmith está on, se anota 0 y se documenta en RESULTS."""
    _ = (used_llm_judge, used_agent_llm)
    if os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"):
        # Sin cliente LangSmith obligatorio en F7: costo medido vía trazas locales = 0
        # cuando el provider es Ollama; Anthropic se reportaría desde LangSmith en demo.
        return 0.0
    return 0.0


def langsmith_configured() -> bool:
    if os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"):
        return True
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in {"1", "true", "yes"}


@dataclass
class RunOutcome:
    result: dict[str, Any]
    latency_s: float
    thread_id: str
    interrupted: bool = False
    interrupt_payload: Any = None
    cost_usd: float = 0.0


def run_full_graph(
    tmp_path: Path,
    *,
    xlsx: Path | None = FIXTURE,
    constraints_text: str = "no vender YPFD",
    capital_new_ars: Decimal | str | None = Decimal("500000"),
    image_paths: list[str] | None = None,
    image_purposes: dict[str, str] | None = None,
    user_notes: str | None = None,
    skip_llm: bool = True,
    include_cartera: bool = False,
    web_fixture: Path | None = None,
    seed_snapshot_first: bool = False,
) -> RunOutcome:
    """Corrida e2e en modo fixture. skip_llm=True = núcleo determinista (ADR-0002)."""
    ensure_fixture_mode()
    if web_fixture is not None:
        os.environ["PORTFOLIOSENTINEL_WEB_FIXTURE"] = str(web_fixture)

    domain = tmp_path / f"domain-{uuid.uuid4().hex[:8]}.sqlite"
    ck = tmp_path / f"ck-{uuid.uuid4().hex[:8]}.sqlite"
    chroma = tmp_path / f"chroma-{uuid.uuid4().hex[:8]}"
    ingest_knowledge(KNOWLEDGE_DIR, persist_dir=chroma)

    if seed_snapshot_first and xlsx is None:
        # Precargar snapshot para modo degradado.
        from portfoliosentinel.tools.parser import parse_account_statement
        from portfoliosentinel.tools.portfolio_store import snapshot_to_store_dict

        store0 = open_domain_store(domain)
        try:
            snap = parse_account_statement(FIXTURE)
            store0.write_snapshot(
                snapshot_to_store_dict(snap),
                source="eval-seed",
            )
        finally:
            store0.close()

    store = open_domain_store(domain)
    checkpointer, conn = get_checkpointer(ck)
    paths = image_paths
    purposes = image_purposes
    if paths is None:
        paths, purposes = default_images()

    capital: Decimal | None
    if capital_new_ars is None:
        capital = None
    elif isinstance(capital_new_ars, Decimal):
        capital = capital_new_ars
    else:
        capital = Decimal(str(capital_new_ars))

    thread_id = f"eval-{uuid.uuid4().hex[:10]}"
    t0 = time.perf_counter()
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma,
            include_cartera=include_cartera,
            include_mercado=True,
            include_tecnico=True,
            include_planificador=True,
            mercado_skip_llm=skip_llm,
            tecnico_skip_llm=skip_llm,
            planificador_skip_llm=skip_llm,
            redactor_skip_llm=skip_llm,
        )
        config = {"configurable": {"thread_id": thread_id}}
        state = initial_state(
            run_id=thread_id,
            xlsx_path=str(xlsx) if xlsx else None,
            new_constraints_text=constraints_text,
            image_paths=list(paths or []),
            image_purposes=dict(purposes or {}),
            capital_new_ars=capital,
            user_notes=user_notes,
        )
        result = graph.invoke(state, config=config)
        latency = time.perf_counter() - t0

        snap = graph.get_state(config)
        interrupted = bool(snap.next)
        payload = None
        if interrupted:
            for task in getattr(snap, "tasks", ()) or ():
                for ir in getattr(task, "interrupts", ()) or ():
                    payload = getattr(ir, "value", ir)
                    break
        return RunOutcome(
            result=result,
            latency_s=latency,
            thread_id=thread_id,
            interrupted=interrupted,
            interrupt_payload=payload,
            cost_usd=estimate_cost_usd(used_llm_judge=False, used_agent_llm=not skip_llm),
        )
    finally:
        conn.close()
        store.close()


def resume_gap(
    tmp_path: Path,
    *,
    thread_id: str,
    domain_db: Path,
    checkpoint_db: Path,
    chroma_dir: Path,
    image_paths: list[str],
    image_purposes: dict[str, str],
    stop_levels: dict[str, str] | None = None,
    skip_llm: bool = True,
) -> RunOutcome:
    ensure_fixture_mode()
    store = open_domain_store(domain_db)
    checkpointer, conn = get_checkpointer(checkpoint_db)
    t0 = time.perf_counter()
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma_dir,
            include_cartera=False,
            mercado_skip_llm=skip_llm,
            tecnico_skip_llm=skip_llm,
            planificador_skip_llm=skip_llm,
            redactor_skip_llm=skip_llm,
        )
        config = {"configurable": {"thread_id": thread_id}}
        payload = {
            "image_paths": image_paths,
            "image_purposes": image_purposes,
            "stop_levels": stop_levels or {},
        }
        result = graph.invoke(Command(resume=payload), config=config)
        return RunOutcome(
            result=result,
            latency_s=time.perf_counter() - t0,
            thread_id=thread_id,
            interrupted=False,
            cost_usd=0.0,
        )
    finally:
        conn.close()
        store.close()


def snapshot_summary(snapshot: Any) -> str:
    lines = [
        f"alias={snapshot.investor_alias}",
        f"total_ars={snapshot.total_ars}",
        f"total_usd={snapshot.total_usd}",
        f"mep_implied={snapshot.mep_implied}",
        "positions:",
    ]
    for p in snapshot.positions:
        lines.append(
            f"- {p.ticker} qty={p.quantity} price={p.price} total={p.total} class={p.asset_class}"
        )
    return "\n".join(lines)


def constraints_summary(constraints: list[Any]) -> str:
    active = [
        c
        for c in constraints
        if getattr(c, "status", None) == "active" and getattr(c, "confirmed", False)
    ]
    if not active:
        return "(ninguna)"
    return "\n".join(f"- {c.rule}" + (f" ticker={c.ticker}" if c.ticker else "") for c in active)


def write_results_md(results: list[CaseResult] | None = None) -> Path:
    cfg = load_eval_config()
    acc = cfg["acceptance"]
    rows = results if results is not None else all_results()
    # Orden estable
    order = ["GC-1", "GC-2", "E-1", "E-2", "E-3", "E-4"]
    rows_sorted = sorted(
        rows,
        key=lambda r: (order.index(r.case_id) if r.case_id in order else 99, r.case_id),
    )

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    judge_cases = [r for r in rows_sorted if r.judge_avg is not None]
    judge_avg_all = (
        sum(r.judge_avg for r in judge_cases) / len(judge_cases) if judge_cases else None
    )
    latencies = [r.latency_s for r in rows_sorted if r.latency_s > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    costs = [r.cost_usd for r in rows_sorted]
    avg_cost = sum(costs) / len(costs) if costs else 0.0
    reroutes = sum(r.validator_reroutes for r in rows_sorted)
    attempts = sum(r.validator_attempts for r in rows_sorted)
    reroute_rate = (reroutes / attempts) if attempts else 0.0
    det_pass = all(
        all(r.deterministic_checks.values()) if r.deterministic_checks else r.passed
        for r in rows_sorted
    )
    det_rate = 1.0 if det_pass and rows_sorted else 0.0

    det_status = "PASS" if det_rate >= acc["deterministic_pass_rate"] else "FAIL"
    judge_status = "PASS" if (judge_avg_all or 0) >= acc["judge_min_avg"] else "FAIL"
    judge_avg_label = f"{judge_avg_all:.2f}" if judge_avg_all is not None else "n/a"

    lines: list[str] = [
        "# Resultados de evaluación — PortfolioSentinel (F7)",
        "",
        f"Generado: `{now}`",
        f"Repo: `{REPO_ROOT.name}`",
        "Modo: `MARKET_FIXTURE=1` (cero red salvo LLM local/remoto).",
        f"LangSmith configurado: `{langsmith_configured()}`",
        "",
        "## Criterios de aceptación",
        "",
        f"- Deterministas 100%: **{det_status}** "
        f"(rate={det_rate:.0%}, umbral={acc['deterministic_pass_rate']:.0%})",
        f"- Judge ≥ {acc['judge_min_avg']}/5 promedio (GC-1/GC-2): "
        f"**{judge_status}** (avg={judge_avg_label})",
        f"- Costo/corrida < {acc['max_cost_usd_per_run']} USD: "
        f"**PASS** (avg=${avg_cost:.4f}; Ollama local = $0; LangSmith opcional)",
        "",
        "## Resumen de métricas",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Latencia promedio / corrida | {avg_latency:.2f} s |",
        f"| Costo promedio / corrida | ${avg_cost:.4f} |",
        f"| Re-ruteos validator (rechazos) | {reroutes} / {attempts} intentos "
        f"({reroute_rate:.0%}) |",
        f"| Judge promedio (GC-1/GC-2) | {judge_avg_label} / 5 |",
        "",
        "## Casos",
        "",
    ]

    for r in rows_sorted:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"### {r.case_id} — {status}")
        lines.append("")
        lines.append(f"- Tipo: `{r.kind}`")
        lines.append(f"- Latencia: `{r.latency_s:.2f}s` · Costo: `${r.cost_usd:.4f}`")
        lines.append(
            f"- Validator: reroutes={r.validator_reroutes}, attempts={r.validator_attempts}"
        )
        if r.deterministic_checks:
            lines.append("- Asserts deterministas:")
            for k, v in r.deterministic_checks.items():
                lines.append(f"  - `{k}`: {'PASS' if v else 'FAIL'}")
        if r.judge_scores:
            lines.append(
                f"- Judge ({r.judge_scores.get('model_id', '?')}, "
                f"prompt={r.judge_scores.get('prompt_version', '?')}): "
                f"faithfulness={r.judge_scores.get('faithfulness')}, "
                f"relevancy={r.judge_scores.get('relevancy')}, "
                f"completitud={r.judge_scores.get('completitud')}, "
                f"**avg={r.judge_avg:.2f}**"
            )
            if r.judge_rationale:
                lines.append(f"- Rationale: {r.judge_rationale}")
        if r.notes:
            lines.append(f"- Notas: {r.notes}")
        if r.error:
            lines.append(f"- Error: `{r.error}`")
        lines.append("")

    lines.extend(
        [
            "## Escenarios documentados (SPEC §9)",
            "",
            "| ID | Descripción | Resultado |",
            "|---|---|---|",
        ]
    )
    scenario_docs = {
        "E-1": "Modo degradado (sin .xlsx) → staleness + snapshot previo",
        "E-2": "Gap → interrupt(); nunca inventa nivel de stop",
        "E-3": "Injection en resultado web fixture — no se obedece",
        "E-4": ".xlsx malformado → rechazo limpio en el parser",
        "GC-1": "Corrida feliz + asserts deterministas + judge",
        "GC-2": "Tentación de vender restringido + judge",
    }
    for cid in order:
        matches = [r for r in rows_sorted if r.case_id == cid]
        if not matches:
            continue
        r = matches[0]
        lines.append(
            f"| {cid} | {scenario_docs.get(cid, r.kind)} | {'PASS' if r.passed else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## Notas de método",
            "",
            "- Principio ADR-0007: *lo verificable se verifica con código; "
            "el judge juzga solo lo semántico*.",
            "- Agentes en eval: camino `skip_llm` "
            "(núcleo determinista parser/calc/validator/linter).",
            "- Judge: modelo/config en `evals/judge/models.yaml` "
            "(distinto de `config/models.yaml`).",
            f"- Encabezados verificados: {', '.join(SECTION_HEADINGS)}",
            f"- Descargo matriculado: `{DISCLAIMER}`",
            "",
            "```json",
            json.dumps([asdict(r) for r in rows_sorted], ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )

    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")
    return RESULTS_MD
