"""E-1 — modo degradado (sin .xlsx)."""

from __future__ import annotations

from pathlib import Path

from evals.harness import CaseResult, count_validator_reroutes, record_result, run_full_graph


def test_e1_degraded_mode(tmp_path: Path):
    # Escenario de control: asserts de degradado/staleness — sin LLM (costo profe).
    outcome = run_full_graph(
        tmp_path,
        xlsx=None,
        skip_llm=True,
        seed_snapshot_first=True,
        constraints_text="no vender YPFD",
    )
    result = outcome.result
    reroutes, attempts = count_validator_reroutes(result.get("validator_traces"))

    checks = {
        "degraded_mode": bool(result.get("degraded_mode")),
        "snapshot_cargado": result.get("snapshot") is not None,
        "staleness": result.get("staleness") is not None,
        "warning_desactualizado": bool(
            result.get("staleness") and "desactualiz" in (result["staleness"].warning or "").lower()
        ),
        "informe_emitido": result.get("report") is not None,
    }
    assert all(checks.values()), f"E-1 FAIL: {checks}"

    record_result(
        CaseResult(
            case_id="E-1",
            kind="scenario",
            passed=True,
            deterministic_checks=checks,
            latency_s=outcome.latency_s,
            cost_usd=outcome.cost_usd,
            validator_reroutes=reroutes,
            validator_attempts=attempts,
            notes="Sin .xlsx: último snapshot + marca de staleness (skip_llm stubs).",
        )
    )
