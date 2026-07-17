"""CLI de PortfolioSentinel — corrida F2 mínima con checkpointer."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from portfoliosentinel.config.settings import DEFAULT_CHECKPOINT_DB, DEFAULT_FIXTURE_XLSX
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import Diagnosis, PortfolioState, RunInputs


def _dec(v: Decimal) -> str:
    return format(v, "f")


def _pct(weight: Decimal) -> str:
    return f"{(weight * Decimal('100')).quantize(Decimal('0.01'))}%"


def format_radiografia(diagnosis: Diagnosis, *, run_id: str, thread_id: str) -> str:
    lines = [
        "=== Radiografía de cartera (F2) ===",
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


def _initial_state(*, xlsx: Path, run_id: str) -> PortfolioState:
    return {
        "run_id": run_id,
        "inputs": RunInputs(xlsx_path=str(xlsx)),
        "snapshot": None,
        "degraded_mode": False,
        "constraints": [],
        "prev_snapshot": None,
        "diagnosis": None,
        "market_context": None,
        "technical_readings": [],
        "plan": None,
        "validation": None,
        "a2a_review": None,
        "info_gaps": [],
        "report": None,
    }


def cmd_run(args: argparse.Namespace) -> int:
    xlsx = Path(args.xlsx)
    if not xlsx.is_file():
        raise SystemExit(f"No existe el .xlsx: {xlsx}")

    thread_id = args.thread_id or str(uuid.uuid4())
    run_id = args.run_id or thread_id
    db_path = Path(args.checkpoint_db)
    interrupt_after = [args.stop_after] if args.stop_after else None

    checkpointer, conn = get_checkpointer(db_path)
    try:
        graph = build_graph(checkpointer=checkpointer, interrupt_after=interrupt_after)
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(_initial_state(xlsx=xlsx, run_id=run_id), config=config)
        diagnosis = result.get("diagnosis")

        if diagnosis is None:
            pause = f" tras '{args.stop_after}'" if args.stop_after else ""
            print(
                f"[checkpoint] Corrida pausada{pause}. thread_id={thread_id} db={db_path}",
                flush=True,
            )
            snap = result.get("snapshot")
            if snap is not None:
                print(
                    f"  snapshot: {len(snap.positions)} posiciones, "
                    f"total_ars={snap.total_ars}, mep={snap.mep_implied}",
                    flush=True,
                )
            return 0

        print(format_radiografia(diagnosis, run_id=run_id, thread_id=thread_id))
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


def cmd_inspect(args: argparse.Namespace) -> int:
    db_path = Path(args.checkpoint_db)
    checkpointer, conn = get_checkpointer(db_path)
    try:
        graph = build_graph(checkpointer=checkpointer)
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
        }
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


def cmd_resume(args: argparse.Namespace) -> int:
    db_path = Path(args.checkpoint_db)
    checkpointer, conn = get_checkpointer(db_path)
    try:
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": args.thread_id}}
        result = graph.invoke(None, config=config)
        diagnosis = result.get("diagnosis")
        run_id = result.get("run_id", args.thread_id)
        if diagnosis is None:
            print("Resume terminó sin diagnosis (¿sigue pausado?)")
            return 1
        print(format_radiografia(diagnosis, run_id=run_id, thread_id=args.thread_id))
        return 0
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="portfoliosentinel", description="PortfolioSentinel CLI")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Corrida F2: parser → orquestador → analista de cartera")
    run.add_argument("--xlsx", type=str, default=str(DEFAULT_FIXTURE_XLSX))
    run.add_argument("--thread-id", type=str, default=None)
    run.add_argument("--run-id", type=str, default=None)
    run.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    run.add_argument(
        "--stop-after",
        type=str,
        default=None,
        choices=["parser", "orquestador"],
        help="Pausa tras el nodo (checkpoint) para demo de inspección",
    )
    run.set_defaults(func=cmd_run)

    insp = sub.add_parser("inspect", help="Inspecciona estado checkpointeado por thread_id")
    insp.add_argument("--thread-id", type=str, required=True)
    insp.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    insp.set_defaults(func=cmd_inspect)

    nxt = sub.add_parser("resume", help="Reanuda una corrida pausada por thread_id")
    nxt.add_argument("--thread-id", type=str, required=True)
    nxt.add_argument("--checkpoint-db", type=str, default=str(DEFAULT_CHECKPOINT_DB))
    nxt.set_defaults(func=cmd_resume)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
