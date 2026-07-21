"""CLI de PortfolioSentinel — corrida F4 con market-data + RAG + store."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.types import Command

from portfoliosentinel.config.settings import (
    DEFAULT_CHECKPOINT_DB,
    DEFAULT_DOMAIN_DB,
    DEFAULT_FIXTURE_XLSX,
)
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import Diagnosis, PortfolioState, RunInputs
from portfoliosentinel.tools.portfolio_store import open_domain_store


def _dec(v: Decimal) -> str:
    return format(v, "f")


def _pct(weight: Decimal) -> str:
    return f"{(weight * Decimal('100')).quantize(Decimal('0.01'))}%"


def format_radiografia(diagnosis: Diagnosis, *, run_id: str, thread_id: str) -> str:
    lines = [
        "=== Radiografía de cartera ===",
        f"run_id={run_id}  thread_id={thread_id}",
        "",
        f"MEP implícito: {_dec(diagnosis.mep_implied)}",
        "",
        "Pesos por clase:",
    ]
    for cw in diagnosis.class_weights:
        lines.append(f"  - {cw.asset_class}: {_dec(cw.total_ars)} ARS ({_pct(cw.weight)})")
    lines.append("")
    lines.append("Pesos por posición:")
    for pw in diagnosis.position_weights:
        lines.append(
            f"  - {pw.ticker} [{pw.asset_class}]: {_dec(pw.total_ars)} ARS ({_pct(pw.weight)})"
        )
    lines.append("")
    lines.append("Clusters semánticos (driver de riesgo):")
    for cl in diagnosis.clusters:
        tickers = ", ".join(cl.tickers)
        lines.append(
            f"  - {cl.name} [{cl.driver}]: {tickers} — {_dec(cl.total_ars)} ARS ({_pct(cl.weight)})"
        )
    lines.append("")
    lines.append("Concentraciones:")
    for note in diagnosis.concentrations:
        lines.append(f"  - {note}")
    lines.append("")
    lines.append(f"Diagnóstico: {diagnosis.structural_diagnosis}")
    return "\n".join(lines)


def _langsmith_configured() -> bool:
    if os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"):
        return True
    return os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in {"1", "true", "yes"}


def _initial_state(
    *,
    xlsx: Path | None,
    run_id: str,
    auto_confirm: bool,
    constraints_text: str | None,
    image_paths: list[str] | None = None,
    image_purposes: dict[str, str] | None = None,
    capital_new_ars: str | None = None,
    user_notes: str | None = None,
) -> PortfolioState:
    capital = Decimal(capital_new_ars) if capital_new_ars else None
    return {
        "run_id": run_id,
        "inputs": RunInputs(
            xlsx_path=str(xlsx) if xlsx else None,
            auto_confirm_constraints=auto_confirm,
            new_constraints_text=constraints_text,
            image_paths=list(image_paths or []),
            image_purposes=dict(image_purposes or {}),
            capital_new_ars=capital,
            user_notes=user_notes,
        ),
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


def _print_interrupt_payload(payload: Any) -> None:
    kind = payload.get("type") if isinstance(payload, dict) else None
    title = {
        "constraint_echo_back": "Echo-back de restricciones (HITL)",
        "info_gaps": "Info gaps — faltan gráficos/stops (HITL)",
        "validation_escalate": "Validator — escala a usuario (HITL)",
    }.get(kind or "", "Interrupt HITL")
    print(f"\n=== {title} ===", flush=True)
    if isinstance(payload, dict):
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    else:
        print(payload, flush=True)
    print(
        "Reanudá con: portfoliosentinel resume --thread-id <id> ...",
        flush=True,
    )


def cmd_run(args: argparse.Namespace) -> int:
    if getattr(args, "market_fixture", False):
        os.environ["MARKET_FIXTURE"] = "1"

    xlsx: Path | None
    if args.no_xlsx:
        xlsx = None
    else:
        xlsx = Path(args.xlsx)
        if not xlsx.is_file():
            raise SystemExit(f"No existe el .xlsx: {xlsx}")

    thread_id = args.thread_id or str(uuid.uuid4())
    run_id = args.run_id or thread_id
    db_path = Path(args.checkpoint_db)
    domain_db = Path(args.domain_db)
    interrupt_after = [args.stop_after] if args.stop_after else None
    auto_confirm = bool(args.confirm_constraints)

    image_paths: list[str] = []
    image_purposes: dict[str, str] = {}
    if getattr(args, "image", None):
        for spec in args.image:
            # formato path::purpose
            if "::" in spec:
                path, purpose = spec.split("::", 1)
            else:
                path, purpose = spec, "unspecified"
            image_paths.append(path)
            image_purposes[path] = purpose

    store = open_domain_store(domain_db)
    checkpointer, conn = get_checkpointer(db_path)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            interrupt_after=interrupt_after,
            tecnico_skip_llm=bool(getattr(args, "skip_llm", False)),
            planificador_skip_llm=bool(getattr(args, "skip_llm", False)),
            mercado_skip_llm=bool(getattr(args, "skip_llm", False)),
            redactor_skip_llm=bool(getattr(args, "skip_llm", False)),
            include_cartera=not bool(getattr(args, "skip_llm", False)),
        )
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(
            _initial_state(
                xlsx=xlsx,
                run_id=run_id,
                auto_confirm=auto_confirm,
                constraints_text=args.constraint,
                image_paths=image_paths,
                image_purposes=image_purposes,
                capital_new_ars=getattr(args, "capital_new", None),
                user_notes=getattr(args, "notes", None),
            ),
            config=config,
        )

        # Si quedó en interrupt de echo-back:
        state_snap = graph.get_state(config)
        if state_snap.next and not result.get("report"):
            tasks = getattr(state_snap, "tasks", ()) or ()
            for task in tasks:
                interrupts = getattr(task, "interrupts", ()) or ()
                for ir in interrupts:
                    _print_interrupt_payload(getattr(ir, "value", ir))
            print(
                f"[checkpoint] Esperando confirmación de restricciones. thread_id={thread_id}",
                flush=True,
            )
            return 0

        diagnosis = result.get("diagnosis")
        if diagnosis is None and args.stop_after:
            print(
                f"[checkpoint] Corrida pausada tras '{args.stop_after}'. "
                f"thread_id={thread_id} db={db_path}",
                flush=True,
            )
            snap = result.get("snapshot")
            if snap is not None:
                print(
                    f"  snapshot: {len(snap.positions)} posiciones, "
                    f"total_ars={snap.total_ars}, mep={snap.mep_implied}",
                    flush=True,
                )
            if result.get("degraded_mode"):
                print(f"  degraded_mode=True  staleness={result.get('staleness')}", flush=True)
            return 0

        if diagnosis is not None:
            print(format_radiografia(diagnosis, run_id=run_id, thread_id=thread_id))
        if result.get("degraded_mode"):
            st = result.get("staleness")
            print("\n[degraded] modo degradado activo", flush=True)
            if st is not None:
                print(f"  {st.warning}", flush=True)
        if result.get("report"):
            print("\n--- Informe final (linter OK) ---", flush=True)
            print(result["report"], flush=True)
        elif result.get("report_lint") is not None and not result["report_lint"].approved:
            print("\n--- Informe NO emitido (linter rechazó) ---", flush=True)
            print(json.dumps(result["report_lint"].model_dump(), ensure_ascii=False, indent=2))
        if result.get("report_lint_traces"):
            print("\n=== Trazas report linter ===", flush=True)
            print(
                json.dumps(result["report_lint_traces"], ensure_ascii=False, indent=2),
                flush=True,
            )
        mc = result.get("market_context")
        if mc is not None:
            print("\n=== Contexto de mercado ===", flush=True)
            print(mc.summary, flush=True)
            if mc.mep_warning:
                print(f"\n[WARNING MEP] {mc.mep_warning}", flush=True)
            if mc.citations:
                print("Citas:", flush=True)
                for c in mc.citations:
                    print(f"  - [{c.get('source_id')}] {c.get('note')}", flush=True)
        plan = result.get("plan")
        if plan is not None:
            print("\n=== Plan de rebalanceo ===", flush=True)
            print(plan.reasoning, flush=True)
            for a in plan.actions:
                print(
                    f"  - {a.ticker}: {a.action}"
                    + (f" qty={a.quantity}" if a.quantity is not None else "")
                    + (f" stop={a.stop_level}" if a.stop_level is not None else ""),
                    flush=True,
                )
            if plan.ml_inputs:
                print("Insumos predict_trend:", flush=True)
                for m in plan.ml_inputs:
                    print(f"  - {m.note}", flush=True)
        if result.get("validator_traces"):
            print("\n=== Trazas validator ===", flush=True)
            print(json.dumps(result["validator_traces"], ensure_ascii=False, indent=2), flush=True)
        if _langsmith_configured():
            print("\n[observabilidad] LangSmith configurado (env vars presentes).")
        else:
            print(
                "\n[observabilidad] LangSmith NO configurado "
                "(sin LANGSMITH_API_KEY / LANGCHAIN_API_KEY)."
            )
        return 0
    finally:
        conn.close()
        store.close()


def cmd_inspect(args: argparse.Namespace) -> int:
    db_path = Path(args.checkpoint_db)
    domain_db = Path(args.domain_db)
    checkpointer, conn = get_checkpointer(db_path)
    store = open_domain_store(domain_db)
    try:
        graph = build_graph(checkpointer=checkpointer, store=store)
        config = {"configurable": {"thread_id": args.thread_id}}
        snap = graph.get_state(config)
        if snap is None or snap.values is None or not snap.values:
            print(f"No hay estado checkpointeado para thread_id={args.thread_id}")
            return 1

        values = snap.values
        payload: dict[str, Any] = {
            "thread_id": args.thread_id,
            "next": list(snap.next) if snap.next else [],
            "run_id": values.get("run_id"),
            "degraded_mode": values.get("degraded_mode"),
            "has_snapshot": values.get("snapshot") is not None,
            "has_diagnosis": values.get("diagnosis") is not None,
            "has_report": values.get("report") is not None,
            "constraints": [c.model_dump() for c in (values.get("constraints") or [])],
        }
        staleness = values.get("staleness")
        if staleness is not None:
            payload["staleness"] = staleness.model_dump()
        snapshot = values.get("snapshot")
        if snapshot is not None:
            payload["snapshot"] = {
                "investor_alias": snapshot.investor_alias,
                "positions": len(snapshot.positions),
                "total_ars": str(snapshot.total_ars),
                "total_usd": str(snapshot.total_usd),
                "mep_implied": str(snapshot.mep_implied),
                "tickers": [p.ticker for p in snapshot.positions],
            }
        diagnosis = values.get("diagnosis")
        if diagnosis is not None:
            payload["diagnosis"] = {
                "mep_implied": str(diagnosis.mep_implied),
                "clusters": [
                    {"name": c.name, "tickers": c.tickers, "weight": str(c.weight)}
                    for c in diagnosis.clusters
                ],
                "structural_diagnosis": diagnosis.structural_diagnosis,
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        conn.close()
        store.close()


def cmd_resume(args: argparse.Namespace) -> int:
    db_path = Path(args.checkpoint_db)
    domain_db = Path(args.domain_db)
    checkpointer, conn = get_checkpointer(db_path)
    store = open_domain_store(domain_db)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            tecnico_skip_llm=bool(getattr(args, "skip_llm", False)),
            planificador_skip_llm=bool(getattr(args, "skip_llm", False)),
            mercado_skip_llm=bool(getattr(args, "skip_llm", False)),
            redactor_skip_llm=bool(getattr(args, "skip_llm", False)),
            include_cartera=not bool(getattr(args, "skip_llm", False)),
        )
        config = {"configurable": {"thread_id": args.thread_id}}

        # Detectar tipo de interrupt pendiente
        snap = graph.get_state(config)
        interrupt_type = None
        for task in getattr(snap, "tasks", ()) or ():
            for ir in getattr(task, "interrupts", ()) or ():
                val = getattr(ir, "value", ir)
                if isinstance(val, dict) and "type" in val:
                    interrupt_type = val["type"]

        if interrupt_type == "info_gaps":
            image_paths: list[str] = []
            image_purposes: dict[str, str] = {}
            if args.image:
                for spec in args.image:
                    if "::" in spec:
                        path, purpose = spec.split("::", 1)
                    else:
                        path, purpose = spec, "stop_chart"
                    image_paths.append(path)
                    image_purposes[path] = purpose
            stop_levels: dict[str, str] = {}
            if args.stop_level:
                for spec in args.stop_level:
                    ticker, level = spec.split("=", 1)
                    stop_levels[ticker.upper()] = level
            resume_payload: dict[str, Any] = {
                "image_paths": image_paths,
                "image_purposes": image_purposes,
                "stop_levels": stop_levels,
            }
        elif interrupt_type == "validation_escalate":
            resume_payload = {"action": args.escalate_action or "accept_risk"}
        else:
            resume_payload = {"action": "confirm_all"}
            if args.revoke_ids:
                resume_payload = {
                    "action": "confirm",
                    "revoke_ids": [x.strip() for x in args.revoke_ids.split(",") if x.strip()],
                    "confirm_ids": None,
                }

        result = graph.invoke(Command(resume=resume_payload), config=config)

        # Si sigue pausado (otro interrupt), mostrarlo
        state_snap = graph.get_state(config)
        if state_snap.next:
            for task in getattr(state_snap, "tasks", ()) or ():
                for ir in getattr(task, "interrupts", ()) or ():
                    _print_interrupt_payload(getattr(ir, "value", ir))
            return 0

        diagnosis = result.get("diagnosis")
        run_id = result.get("run_id", args.thread_id)
        if diagnosis is not None:
            print(format_radiografia(diagnosis, run_id=run_id, thread_id=args.thread_id))
        plan = result.get("plan")
        if plan is not None:
            print("\n=== Plan de rebalanceo ===")
            for a in plan.actions:
                print(
                    f"  - {a.ticker}: {a.action}"
                    + (f" qty={a.quantity}" if a.quantity is not None else "")
                    + (f" stop={a.stop_level}" if a.stop_level is not None else "")
                )
        if result.get("report"):
            print("\n--- Informe final (linter OK) ---")
            print(result["report"])
        elif result.get("report_lint") is not None and not result["report_lint"].approved:
            print("\n--- Informe NO emitido (linter rechazó) ---")
            print(json.dumps(result["report_lint"].model_dump(), ensure_ascii=False, indent=2))
        if diagnosis is None and not result.get("report") and plan is None:
            print("Resume terminó sin diagnosis/plan/report (¿sigue pausado?)")
            return 1
        return 0
    finally:
        conn.close()
        store.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="portfoliosentinel", description="PortfolioSentinel CLI")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Corrida F6: redactor + linter + persistencia")
    run.add_argument("--xlsx", type=str, default=str(DEFAULT_FIXTURE_XLSX))
    run.add_argument(
        "--no-xlsx",
        action="store_true",
        help="Modo degradado: usa el último snapshot del store de dominio",
    )
    run.add_argument("--thread-id", type=str, default=None)
    run.add_argument("--run-id", type=str, default=None)
    run.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    run.add_argument("--domain-db", type=str, default=str(DEFAULT_DOMAIN_DB))
    run.add_argument(
        "--constraint",
        type=str,
        default=None,
        help='Texto de restricción nueva, ej. "no vender YPFD"',
    )
    run.add_argument(
        "--confirm-constraints",
        action="store_true",
        help="Auto-confirma el echo-back (sin interrupt HITL)",
    )
    run.add_argument(
        "--market-fixture",
        action="store_true",
        help="MARKET_FIXTURE=1: FX/quotes/web desde disco (sin red salvo LLM)",
    )
    run.add_argument(
        "--image",
        action="append",
        default=None,
        help="Imagen path::purpose (repetible). Propósito lo declara el usuario.",
    )
    run.add_argument("--capital-new", type=str, default=None, help="Capital nuevo ARS")
    run.add_argument("--notes", type=str, default=None, help="Notas libres del usuario")
    run.add_argument(
        "--skip-llm",
        action="store_true",
        help="Modo determinista (sin cartera/LLM; stubs técnico+plan+redactor)",
    )
    run.add_argument(
        "--stop-after",
        type=str,
        default=None,
        choices=["intake", "orquestador"],
        help="Pausa tras el nodo (checkpoint) para demo de inspección",
    )
    run.set_defaults(func=cmd_run)

    insp = sub.add_parser("inspect", help="Inspecciona estado checkpointeado por thread_id")
    insp.add_argument("--thread-id", type=str, required=True)
    insp.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    insp.add_argument("--domain-db", type=str, default=str(DEFAULT_DOMAIN_DB))
    insp.set_defaults(func=cmd_inspect)

    nxt = sub.add_parser("resume", help="Reanuda una corrida pausada por thread_id")
    nxt.add_argument("--thread-id", type=str, required=True)
    nxt.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    nxt.add_argument("--domain-db", type=str, default=str(DEFAULT_DOMAIN_DB))
    nxt.add_argument(
        "--confirm-constraints",
        action="store_true",
        default=True,
        help="Confirma todas las restricciones del echo-back (default)",
    )
    nxt.add_argument(
        "--revoke-ids",
        type=str,
        default=None,
        help="IDs de restricciones a revocar (comma-separated)",
    )
    nxt.add_argument(
        "--image",
        action="append",
        default=None,
        help="Para info_gaps: path::purpose (repetible)",
    )
    nxt.add_argument(
        "--stop-level",
        action="append",
        default=None,
        help="Para info_gaps: TICKER=nivel (repetible)",
    )
    nxt.add_argument(
        "--escalate-action",
        type=str,
        default="accept_risk",
        help="Para validation_escalate: accept_risk | provide_guidance",
    )
    nxt.add_argument(
        "--skip-llm",
        action="store_true",
        help="Debe coincidir con la corrida original si usó stubs",
    )
    nxt.set_defaults(func=cmd_resume)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
