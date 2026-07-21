"""DoD F6: informe 7 secciones vía linter, rechazo por regla YAML, persistencia+RAG."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from portfoliosentinel.config.settings import (
    CONFIG_DIR,
    DEFAULT_FIXTURE_XLSX,
    DEFAULT_IMAGES_DIR,
    KNOWLEDGE_DIR,
)
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.report_builder import (
    DISCLAIMER,
    SECTION_HEADINGS,
    build_deterministic_report,
)
from portfoliosentinel.graph.state import Constraint, RunInputs
from portfoliosentinel.rag.ingest import ingest_knowledge
from portfoliosentinel.rag.retriever import retrieve
from portfoliosentinel.tools.guardrails import lint_report, load_guardrails
from portfoliosentinel.tools.parser import parse_account_statement
from portfoliosentinel.tools.portfolio_store import open_domain_store

FIXTURE = DEFAULT_FIXTURE_XLSX
IMAGES = DEFAULT_IMAGES_DIR
GUARDRAILS = CONFIG_DIR / "guardrails.yaml"


def _initial_state(**input_kw):
    run_id = input_kw.pop("run_id", f"f6-{uuid.uuid4().hex[:8]}")
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


@pytest.fixture(scope="module")
def snapshot():
    assert FIXTURE.is_file()
    return parse_account_statement(FIXTURE)


@pytest.fixture(scope="module")
def report_rule_ids():
    load_guardrails.cache_clear()
    cfg = yaml.safe_load(GUARDRAILS.read_text(encoding="utf-8"))
    ids = [r["id"] for r in cfg["report_rules"]]
    assert ids == [
        "no-sell-restricted",
        "qty-within-holdings",
        "disclaimer-present",
        "no-execution-language",
        "report-structure",
    ]
    return ids


def _clean_report(snapshot) -> str:
    constraints = [
        Constraint(
            rule="no vender YPFD",
            ticker="YPFD",
            status="active",
            confirmed=True,
            source="echo",
        )
    ]
    # Plan mínimo vía grafo skip_llm en tests e2e; acá armamos informe limpio
    # con acciones válidas (sin vender YPFD; qty ≤ tenencia).
    from portfoliosentinel.graph.f5_logic import build_deterministic_plan

    plan, gaps = build_deterministic_plan(
        snapshot=snapshot,
        constraints=constraints,
        diagnosis=None,
        technical_readings=[],
        capital_new_ars=Decimal("100000"),
    )
    return build_deterministic_report(
        run_id="f6-unit",
        snapshot=snapshot,
        constraints=constraints,
        diagnosis=None,
        market_context=None,
        technical_readings=[],
        plan=plan,
        info_gaps=gaps,
        capital_new_ars=Decimal("100000"),
    )


def test_clean_report_passes_linter(snapshot, report_rule_ids):
    report = _clean_report(snapshot)
    for heading in SECTION_HEADINGS:
        assert heading in report
    assert DISCLAIMER.lower() in report.lower()
    constraints = [
        Constraint(rule="no vender YPFD", ticker="YPFD", status="active", confirmed=True)
    ]
    result = lint_report(report, snapshot=snapshot, constraints=constraints, attempt=1)
    assert result.approved is True, result.feedback
    assert result.violations == []


def test_linter_rejects_each_yaml_rule(snapshot, report_rule_ids):
    """DoD: adulterar el informe violando cada report_rule una por una."""
    base = _clean_report(snapshot)
    constraints = [
        Constraint(rule="no vender YPFD", ticker="YPFD", status="active", confirmed=True)
    ]
    assert lint_report(base, snapshot=snapshot, constraints=constraints, attempt=1).approved

    adulterations: dict[str, str] = {}

    # no-sell-restricted: acción estructurada ilegal + verbo libre
    adulterations["no-sell-restricted"] = base + (
        "\n- ticker=YPFD; action=salir; qty=1; ref=adulterado\nAdemás conviene vender YPFD ahora.\n"
    )

    # qty-within-holdings: qty > tenencia de VIST
    vist_qty = next(p.quantity for p in snapshot.positions if p.ticker == "VIST")
    overflow = vist_qty + Decimal("1000")
    adulterations["qty-within-holdings"] = re.sub(
        r"- ticker=VIST; action=salir; qty=[0-9.]+;",
        f"- ticker=VIST; action=salir; qty={overflow};",
        base,
        count=1,
    )
    assert f"qty={overflow}" in adulterations["qty-within-holdings"]

    # disclaimer-present: sacar substrings del descargo
    adulterations["disclaimer-present"] = base.replace(
        "no constituye asesoramiento financiero", "texto genérico"
    ).replace("no ejecuta órdenes", "puede operar")

    # no-execution-language
    adulterations["no-execution-language"] = base + "\nNota: ya ejecuté la orden enviada.\n"

    # report-structure: borrar una sección marcada
    adulterations["report-structure"] = base.replace("## 4. Integración FCI", "## 4. FCI (mal)")

    evidence: list[str] = []
    for rule_id in report_rule_ids:
        bad = adulterations[rule_id]
        result = lint_report(bad, snapshot=snapshot, constraints=constraints, attempt=1)
        assert result.approved is False, f"{rule_id} debió rechazar"
        assert any(v.rule_id == rule_id for v in result.violations), (
            f"{rule_id}: violations={result.violations}"
        )
        msg = next(v.message for v in result.violations if v.rule_id == rule_id)
        evidence.append(f"{rule_id} → REJECT: {msg}")
        print(f"\n=== LINTER REJECT [{rule_id}] ===\n{msg}")

    assert len(evidence) == len(report_rule_ids)


def test_full_run_report_passes_linter_and_persists(tmp_path: Path, snapshot):
    """DoD: corrida completa fixture → 7 secciones (linter) + BD + Chroma."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    chroma = tmp_path / "chroma"
    store = open_domain_store(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        ingest_knowledge(KNOWLEDGE_DIR, persist_dir=chroma)
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma,
            include_cartera=False,
            include_mercado=True,
            include_tecnico=True,
            include_planificador=True,
            mercado_skip_llm=True,
            tecnico_skip_llm=True,
            planificador_skip_llm=True,
            redactor_skip_llm=True,
        )
        thread_id = f"f6-e2e-{uuid.uuid4().hex[:8]}"
        ggal_stop = str(IMAGES / "chart-ggal-with-stop.png")
        fci = str(IMAGES / "fci-panel.png")
        screening = str(IMAGES / "chart-aapl-screening.png")
        result = graph.invoke(
            _initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                new_constraints_text="no vender YPFD",
                image_paths=[ggal_stop, fci, screening],
                image_purposes={
                    ggal_stop: "stop_chart",
                    fci: "tenencia_externa_fci",
                    screening: "screening",
                },
                capital_new_ars=Decimal("500000"),
            ),
            config={"configurable": {"thread_id": thread_id}},
        )

        report = result.get("report")
        assert report is not None, "informe no emitido"
        lint = result.get("report_lint")
        assert lint is not None and lint.approved is True, getattr(lint, "feedback", None)
        for heading in SECTION_HEADINGS:
            assert heading in report, f"falta {heading}"
        assert "Requisitos confirmados" in report
        assert "Decisiones de diseño propuestas" in report
        assert "Acciones_verificables" in report
        assert DISCLAIMER.split()[2] in report.lower() or "asesoramiento" in report.lower()

        # Re-verificar con el linter (no a ojo)
        recheck = lint_report(
            report,
            snapshot=result["snapshot"],
            constraints=list(result.get("constraints") or []),
            attempt=1,
        )
        assert recheck.approved is True, recheck.feedback

        reports = store.list_reports()
        assert len(reports) == 1
        assert reports[0]["run_id"] == thread_id
        assert "## 1. Encabezado" in reports[0]["content_md"]

        hits = retrieve(
            f"Informe PortfolioSentinel {thread_id} Radiografía Plan de acción",
            collection="reports",
            n_results=3,
            persist_dir=chroma,
        )
        assert hits, "informe no indexado / no recuperable"
        assert any(h["id"] == reports[0]["id"] for h in hits)
        print("\n=== F6 e2e: linter OK + BD + Chroma ===")
        print(f"report_id={reports[0]['id']} chars={len(report)}")
    finally:
        conn.close()
        store.close()


def test_rejected_report_does_not_persist(tmp_path: Path, snapshot):
    """Si el linter rechaza tras reintentos, el informe NO sale ni se escribe en BD."""
    from portfoliosentinel.graph.nodes_f6 import report_lint_fail_node, report_linter_node
    from portfoliosentinel.graph.state import ReportLintResult

    domain = tmp_path / "domain.sqlite"
    store = open_domain_store(domain)
    try:
        # Simular estado post-redactor con informe adulterado y intentos agotados.
        bad = _clean_report(snapshot).replace("## 1. Encabezado", "## 1. Mal")
        constraints = [
            Constraint(rule="no vender YPFD", ticker="YPFD", status="active", confirmed=True)
        ]
        state = {
            "run_id": "f6-reject",
            "inputs": RunInputs(xlsx_path=str(FIXTURE), auto_confirm_constraints=True),
            "snapshot": snapshot,
            "constraints": constraints,
            "report": bad,
            "report_lint": ReportLintResult(approved=False, attempt=2, feedback=["prev"]),
            "report_lint_traces": [],
            "report_linter_feedback": [],
            "degraded_mode": False,
        }
        out = report_linter_node(state)  # type: ignore[arg-type]
        assert out["report_lint"].approved is False
        assert out["report"] is None  # no sale
        assert out["report_linter_feedback"]

        # Fail node + persist sin escribir report
        from portfoliosentinel.graph.nodes import persist_node

        fail_out = report_lint_fail_node({**state, **out})  # type: ignore[arg-type]
        persist_out = persist_node(
            {
                **state,
                **out,
                **fail_out,
                "report_lint": out["report_lint"],
            },  # type: ignore[arg-type]
            store=store,
            chroma_dir=tmp_path / "chroma",
        )
        assert persist_out["report"] is None
        assert store.list_reports() == []
        print("\n=== Ejemplo rechazo real ===")
        print("\n".join(out["report_linter_feedback"][:3]))
    finally:
        store.close()
