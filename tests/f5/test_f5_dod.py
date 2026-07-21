"""DoD F5: GC-2, interrupt/resume por gap, validator→replan, predict_trend como insumo."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.types import Command

from portfoliosentinel.config.settings import DEFAULT_FIXTURE_XLSX, DEFAULT_IMAGES_DIR, REPO_ROOT
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.f5_logic import build_deterministic_plan, stub_technical_readings
from portfoliosentinel.graph.state import Constraint, Diagnosis, RiskCluster, RunInputs
from portfoliosentinel.tools.calc import PlannedTrade, compute_rebalance
from portfoliosentinel.tools.guardrails import validate_plan
from portfoliosentinel.tools.ml_trend import TrendFeatures, predict_trend
from portfoliosentinel.tools.parser import parse_account_statement

FIXTURE = DEFAULT_FIXTURE_XLSX
IMAGES = DEFAULT_IMAGES_DIR


def _initial_state(**input_kw):
    run_id = input_kw.pop("run_id", f"f5-{uuid.uuid4().hex[:8]}")
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


def test_predict_trend_artifact_loads():
    pred = predict_trend(
        TrendFeatures(rsi_14=70.0, macd_hist=1.0, sma_slope=0.03, return_5d=0.04, volume_z=0.2)
    )
    assert pred.label in {"up", "down", "sideways"}
    assert 0.0 <= pred.proba <= 1.0
    assert pred.model_version
    card = REPO_ROOT / "docs" / "model-card-predict-trend.md"
    assert card.is_file()
    assert "insumo" in card.read_text(encoding="utf-8").lower()


def test_calc_freed_capital_and_cluster_weights(snapshot):
    clusters = [
        RiskCluster(
            name="energía",
            driver="energía argentina",
            tickers=["YPFD", "VIST"],
            total_ars=Decimal("2600000"),
            weight=Decimal("2600000") / snapshot.total_ars,
        )
    ]
    result = compute_rebalance(
        snapshot,
        [PlannedTrade(ticker="VIST", side="sell", quantity=Decimal("10"))],
        capital_new_ars=Decimal("500000"),
        clusters=clusters,
    )
    assert result.capital_freed_ars == Decimal("100000.00")  # 10 * 10000
    assert result.capital_available_ars == Decimal("600000.00")
    energy = next(c for c in result.resulting_cluster_weights if c.name == "energía")
    assert energy.total_ars == Decimal("2500000.00")  # YPFD only


def test_validator_rejects_sell_restricted_and_qty_overflow(snapshot):
    from portfoliosentinel.graph.state import PlanAction, RebalancePlan

    constraints = [
        Constraint(rule="no vender YPFD", ticker="YPFD", status="active", confirmed=True)
    ]
    bad = RebalancePlan(
        actions=[
            PlanAction(
                ticker="YPFD",
                action="salir",
                quantity=Decimal("100"),
                rationale="tentación",
            ),
            PlanAction(
                ticker="GGAL",
                action="reducir",
                quantity=Decimal("999999"),
                rationale="overflow",
            ),
        ]
    )
    result = validate_plan(bad, snapshot=snapshot, constraints=constraints, attempt=1)
    assert result.approved is False
    rule_ids = {v.rule_id for v in result.violations}
    assert "no-sell-restricted" in rule_ids
    assert "qty-within-holdings" in rule_ids


def test_gc2_manual_no_sell_restricted_signals_risk_and_mitigation(snapshot):
    """GC-2-manual: óptimo aparente = vender YPFD; el plan NO lo hace."""
    constraints = [
        Constraint(rule="no vender YPFD", ticker="YPFD", status="active", confirmed=True)
    ]
    diagnosis = Diagnosis(
        class_weights=[],
        position_weights=[],
        mep_implied=snapshot.mep_implied,
        clusters=[
            RiskCluster(
                name="energía argentina",
                driver="energía",
                tickers=["YPFD", "VIST"],
                total_ars=Decimal("2600000"),
                weight=Decimal("2600000") / snapshot.total_ars,
            )
        ],
        concentrations=["YPFD+VIST concentran driver energético"],
        structural_diagnosis="Sobreexposición a energía argentina vía YPFD y VIST.",
    )
    readings = stub_technical_readings(
        [str(IMAGES / "chart-ggal-with-stop.png")],
        {str(IMAGES / "chart-ggal-with-stop.png"): "stop_chart"},
    )
    plan, gaps = build_deterministic_plan(
        snapshot=snapshot,
        constraints=constraints,
        diagnosis=diagnosis,
        technical_readings=readings,
        capital_new_ars=Decimal("1000000"),
    )
    sell_ypfd = [
        a
        for a in plan.actions
        if a.ticker == "YPFD" and a.action in {"salir", "tomar_ganancia_parcial", "reducir"}
    ]
    assert sell_ypfd == [], f"GC-2 FAIL: recomendó vender YPFD: {sell_ypfd}"
    ypfd = next(a for a in plan.actions if a.ticker == "YPFD")
    assert ypfd.action == "mantener"
    assert ypfd.risk_notes, "debe señalar el riesgo"
    assert ypfd.mitigations, "debe proponer mitigación alternativa"
    assert any(a.ticker == "VIST" and a.action == "salir" for a in plan.actions)
    assert plan.ml_inputs, "predict_trend debe figurar como insumo"
    assert "predict_trend" in plan.reasoning
    assert "insumo" in plan.reasoning.lower() or any(m.role == "insumo" for m in plan.ml_inputs)
    # Con stop presente no debería haber gap de GGAL
    assert not any(g.ticker == "GGAL" for g in gaps)


def test_validator_reject_and_replan_trace(tmp_path: Path, snapshot):
    """Provocar violación → traza de rechazo + replan aprobado."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    checkpointer, conn = get_checkpointer(ck)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            domain_db=domain,
            include_cartera=False,
            include_mercado=False,
            include_tecnico=True,
            include_planificador=True,
            tecnico_skip_llm=True,
            planificador_skip_llm=True,
            redactor_skip_llm=True,
        )
        thread_id = f"replan-{uuid.uuid4().hex[:8]}"
        ggal_stop = str(IMAGES / "chart-ggal-with-stop.png")
        result = graph.invoke(
            _initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                new_constraints_text="no vender YPFD",
                image_paths=[ggal_stop],
                image_purposes={ggal_stop: "stop_chart"},
                # Primer plan planta venta ilegal; tras feedback, el stub no la repite.
                user_notes="force_illegal_sell=YPFD",
                capital_new_ars=Decimal("500000"),
            ),
            config={"configurable": {"thread_id": thread_id}},
        )
        traces = result.get("validator_traces") or []
        assert traces, "sin trazas de validator"
        assert traces[0]["approved"] is False
        assert any("YPFD" in fb or "restringido" in fb for fb in traces[0]["feedback"])
        assert result.get("validation") is not None
        assert result["validation"].approved is True
        assert result["validation"].attempt >= 2
        # Evidencia: el plan final no vende YPFD
        plan = result["plan"]
        assert all(
            not (a.ticker == "YPFD" and a.action in {"salir", "reducir", "tomar_ganancia_parcial"})
            for a in plan.actions
        )
        print("\n=== TRACE validator reject+replan ===")
        print(json.dumps(traces, ensure_ascii=False, indent=2))
    finally:
        conn.close()


def test_gap_interrupt_resume_completes_stop(tmp_path: Path):
    """Gap plantado (falta gráfico) → interrupt(); resume con imagen → stop completo."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    checkpointer, conn = get_checkpointer(ck)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            domain_db=domain,
            include_cartera=False,
            include_mercado=False,
            include_tecnico=True,
            include_planificador=True,
            tecnico_skip_llm=True,
            planificador_skip_llm=True,
            redactor_skip_llm=True,
        )
        thread_id = f"gap-{uuid.uuid4().hex[:8]}"
        no_stop = str(IMAGES / "chart-ggal-no-stop.png")
        config = {"configurable": {"thread_id": thread_id}}

        result = graph.invoke(
            _initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                new_constraints_text="no vender YPFD",
                image_paths=[no_stop],
                image_purposes={no_stop: "stop_chart"},
                capital_new_ars=Decimal("0"),
            ),
            config=config,
        )

        state = graph.get_state(config)
        assert state.next, (
            f"se esperaba interrupt por gaps; next={state.next} result_keys={list(result)}"
        )

        # Extraer payload del interrupt
        gap_payload = None
        for task in getattr(state, "tasks", ()) or ():
            for ir in getattr(task, "interrupts", ()) or ():
                val = getattr(ir, "value", ir)
                if isinstance(val, dict) and val.get("type") == "info_gaps":
                    gap_payload = val
        assert gap_payload is not None, "interrupt info_gaps no encontrado"
        assert any(g.get("ticker") == "GGAL" for g in gap_payload["gaps"])
        print("\n=== TRACE gaps interrupt ===")
        print(json.dumps(gap_payload, ensure_ascii=False, indent=2))

        # Antes del resume el plan no debe tener stop inventado
        pre_plan = state.values.get("plan")
        assert pre_plan is not None
        ggal_pre = next(a for a in pre_plan.actions if a.ticker == "GGAL")
        assert ggal_pre.stop_level is None, "BUG CRÍTICO: inventó stop sin gráfico"

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
        plan = resumed.get("plan")
        assert plan is not None
        ggal = next(a for a in plan.actions if a.ticker == "GGAL")
        assert ggal.stop_level == Decimal("6200"), f"stop no completado: {ggal}"
        assert resumed.get("validation") and resumed["validation"].approved
        assert not resumed.get("info_gaps")
        print("\n=== TRACE post-resume GGAL action ===")
        print(ggal.model_dump_json(indent=2))
    finally:
        conn.close()


def test_predict_trend_cited_as_input_not_conclusion(snapshot):
    plan, _ = build_deterministic_plan(
        snapshot=snapshot,
        constraints=[],
        diagnosis=None,
        technical_readings=[],
        capital_new_ars=None,
    )
    assert plan.ml_inputs
    assert "predict_trend" in plan.reasoning
    # No debe ser la única frase / conclusión sin más
    assert "insumo" in plan.reasoning.lower()
    assert any(a.ml_signal_cited for a in plan.actions if a.ticker in {"GGAL", "YPFD", "VIST"})


def test_image_fixtures_exist():
    for name in (
        "fci-panel.png",
        "chart-ggal-no-stop.png",
        "chart-ggal-with-stop.png",
        "chart-aapl-screening.png",
    ):
        assert (IMAGES / name).is_file(), name
