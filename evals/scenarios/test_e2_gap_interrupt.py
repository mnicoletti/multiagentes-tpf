"""E-2 — gap → interrupt(); nunca inventa nivel de stop."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from langgraph.types import Command

from evals.harness import (
    FIXTURE,
    IMAGES,
    CaseResult,
    count_validator_reroutes,
    ensure_fixture_mode,
    gap_images_no_stop,
    initial_state,
    record_result,
)
from portfoliosentinel.config.settings import KNOWLEDGE_DIR
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.rag.ingest import ingest_knowledge
from portfoliosentinel.tools.portfolio_store import open_domain_store


def test_e2_gap_interrupt_never_invents_stop(tmp_path: Path):
    ensure_fixture_mode()
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    chroma = tmp_path / "chroma"
    ingest_knowledge(KNOWLEDGE_DIR, persist_dir=chroma)

    store = open_domain_store(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma,
            include_cartera=False,
            mercado_skip_llm=True,
            tecnico_skip_llm=True,
            planificador_skip_llm=True,
            redactor_skip_llm=True,
        )
        thread_id = f"e2-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        paths, purposes = gap_images_no_stop()

        import time

        t0 = time.perf_counter()
        result = graph.invoke(
            initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                new_constraints_text="no vender YPFD",
                image_paths=paths,
                image_purposes=purposes,
                capital_new_ars=Decimal("500000"),
            ),
            config=config,
        )

        state = graph.get_state(config)
        assert state.next, f"E-2: se esperaba interrupt; next={state.next}"

        gap_payload = None
        for task in getattr(state, "tasks", ()) or ():
            for ir in getattr(task, "interrupts", ()) or ():
                gap_payload = getattr(ir, "value", ir)

        plan = result.get("plan")
        ggal = next((a for a in (plan.actions if plan else []) if a.ticker == "GGAL"), None)
        invented = ggal is not None and ggal.stop_level is not None

        checks = {
            "interrupt_disparado": bool(state.next),
            "payload_info_gaps": isinstance(gap_payload, dict)
            and gap_payload.get("type") == "info_gaps",
            "no_invento_stop_ggal": not invented,
            "info_gaps_en_estado": bool(result.get("info_gaps")),
        }
        assert all(checks.values()), f"E-2 FAIL: {checks} ggal={ggal}"

        # Resume con gráfico que trae stop → completa sin inventar de la nada.
        with_stop = str(IMAGES / "chart-ggal-with-stop.png")
        resumed = graph.invoke(
            Command(
                resume={
                    "image_paths": [with_stop],
                    "image_purposes": {with_stop: "stop_chart"},
                    "stop_levels": {"GGAL": "6200"},
                }
            ),
            config=config,
        )
        latency = time.perf_counter() - t0
        plan2 = resumed.get("plan")
        ggal2 = next((a for a in (plan2.actions if plan2 else []) if a.ticker == "GGAL"), None)
        checks["resume_completa_stop"] = (
            ggal2 is not None and ggal2.stop_level is not None
        ) or resumed.get("report") is not None
        assert checks["resume_completa_stop"]

        reroutes, attempts = count_validator_reroutes(resumed.get("validator_traces"))
        record_result(
            CaseResult(
                case_id="E-2",
                kind="scenario",
                passed=True,
                deterministic_checks=checks,
                latency_s=latency,
                cost_usd=0.0,
                validator_reroutes=reroutes,
                validator_attempts=attempts,
                notes="Gap plantado (chart sin stop) → interrupt(); resume aporta nivel.",
            )
        )
    finally:
        conn.close()
        store.close()
