"""GC-1 — corrida feliz: asserts deterministas + judge semántico."""

from __future__ import annotations

from pathlib import Path

from evals.asserts_det import (
    check_disclaimer,
    check_mep,
    check_parse_exact,
    check_qty_within_holdings,
    check_restriction_respected,
    check_seven_sections,
)
from evals.harness import (
    CaseResult,
    constraints_summary,
    count_validator_reroutes,
    load_eval_config,
    record_result,
    run_full_graph,
    snapshot_summary,
)
from evals.judge import run_judge


def test_gc1_happy_path_deterministic_and_judge(tmp_path: Path):
    cfg = load_eval_config()
    min_avg = float(cfg["acceptance"]["judge_min_avg"])

    # Híbrido anti-quema: sin visión multimodal ni mercado LLM (fixtures).
    # Cartera + planificador + redactor + judge = Anthropic.
    outcome = run_full_graph(
        tmp_path,
        skip_llm=False,
        auto_resume_gaps=True,
        max_gap_resumes=1,
        tecnico_skip_llm=True,
        mercado_skip_llm=True,
        include_cartera=True,
    )
    result = outcome.result
    assert not outcome.interrupted, (
        f"GC-1 sigue en interrupt tras auto-resume "
        f"(resumes={outcome.gap_resumes}): {outcome.interrupt_payload}"
    )
    snapshot = result["snapshot"]
    report = result.get("report")
    plan = result.get("plan")
    constraints = list(result.get("constraints") or [])
    market = result.get("market_context")
    reroutes, attempts = count_validator_reroutes(result.get("validator_traces"))

    checks = {
        "parseo_exacto": check_parse_exact(snapshot),
        "mep": check_mep(snapshot, market),
        "siete_secciones": bool(report) and check_seven_sections(report),
        "descargo": bool(report) and check_disclaimer(report),
        "restriccion_respetada": bool(report)
        and check_restriction_respected(plan, report, constraints),
        "qty_within_holdings": bool(report)
        and check_qty_within_holdings(plan, snapshot, report, constraints),
        "informe_emitido": report is not None,
        "linter_aprobado": bool(result.get("report_lint") and result["report_lint"].approved),
    }

    score = None
    error = None
    passed = False
    try:
        assert all(checks.values()), f"GC-1 deterministas FAIL: {checks}"
        score = run_judge(
            report=report,
            snapshot_summary=snapshot_summary(snapshot),
            constraints_summary=constraints_summary(constraints),
            case_id="GC-1",
        )
        assert score.average >= min_avg, (
            f"Judge GC-1 avg={score.average:.2f} < {min_avg}. "
            f"scores={score.model_dump()} — NO bajar umbral; iterar prompts de agentes."
        )
        passed = True
    except Exception as exc:  # noqa: BLE001 — registramos y re-lanzamos
        error = str(exc)
        raise
    finally:
        record_result(
            CaseResult(
                case_id="GC-1",
                kind="golden",
                passed=passed,
                deterministic_checks=checks,
                judge_scores=(
                    {
                        "faithfulness": score.faithfulness,
                        "relevancy": score.relevancy,
                        "completitud": score.completitud,
                        "model_id": score.model_id,
                        "prompt_version": score.prompt_version,
                    }
                    if score
                    else None
                ),
                judge_avg=score.average if score else None,
                judge_rationale=score.rationale if score else None,
                latency_s=outcome.latency_s,
                cost_usd=outcome.cost_usd,
                validator_reroutes=reroutes,
                validator_attempts=attempts,
                notes=(
                    "GC-1 híbrido: cartera/plan/redactor Anthropic; "
                    f"técnico+mercado stub (anti-visión); gap_resumes={outcome.gap_resumes}."
                ),
                error=error,
            )
        )
