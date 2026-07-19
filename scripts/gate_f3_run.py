"""Corrida F3 sin Analista de Cartera (intake → orquestador → persist)."""
import argparse
import json
import uuid
from pathlib import Path

from langgraph.types import Command

from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import RunInputs
from portfoliosentinel.tools.portfolio_store import open_domain_store


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--domain-db", required=True)
    p.add_argument("--checkpoint-db", required=True)
    p.add_argument("--xlsx", default=None)
    p.add_argument("--no-xlsx", action="store_true")
    p.add_argument("--constraint", default=None)
    p.add_argument("--thread-id", default=None)
    p.add_argument("--auto-confirm", action="store_true")
    p.add_argument("--wait-echo", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--revoke-ids", default=None)
    p.add_argument("--dump-json", default=None)
    args = p.parse_args()

    thread_id = args.thread_id or str(uuid.uuid4())
    store = open_domain_store(args.domain_db)
    cp, conn = get_checkpointer(args.checkpoint_db)
    graph = build_graph(checkpointer=cp, store=store, include_cartera=False)
    config = {"configurable": {"thread_id": thread_id}}

    if args.resume:
        payload = {"action": "confirm_all"}
        if args.revoke_ids:
            payload = {
                "action": "confirm",
                "revoke_ids": [x.strip() for x in args.revoke_ids.split(",") if x.strip()],
                "confirm_ids": None,
            }
        result = graph.invoke(Command(resume=payload), config=config)
    else:
        xlsx = None if args.no_xlsx else args.xlsx
        state = {
            "run_id": thread_id,
            "inputs": RunInputs(
                xlsx_path=xlsx,
                auto_confirm_constraints=bool(args.auto_confirm) and not args.wait_echo,
                new_constraints_text=args.constraint,
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
        }
        result = graph.invoke(state, config=config)

    snap = graph.get_state(config)
    out = {
        "thread_id": thread_id,
        "next": list(snap.next) if snap.next else [],
        "degraded_mode": result.get("degraded_mode"),
        "constraints": [c.model_dump() for c in (result.get("constraints") or [])],
        "staleness": result["staleness"].model_dump() if result.get("staleness") else None,
        "has_snapshot": result.get("snapshot") is not None,
        "snapshot_tickers": (
            [p.ticker for p in result["snapshot"].positions] if result.get("snapshot") else None
        ),
        "has_report": result.get("report") is not None,
        "report_preview": (result.get("report") or "")[:400],
    }
    for task in getattr(snap, "tasks", ()) or ():
        for ir in getattr(task, "interrupts", ()) or ():
            out.setdefault("interrupts", []).append(getattr(ir, "value", ir))

    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.dump_json:
        Path(args.dump_json).write_text(text, encoding="utf-8")
    print(f"\n# thread_id={thread_id}", flush=True)
    conn.close()
    store.close()


if __name__ == "__main__":
    main()
