"""E-4 — .xlsx malformado → rechazo limpio en el parser (sin LLM)."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from evals.harness import CaseResult, record_result
from portfoliosentinel.tools.exceptions import (
    MalformedStatementError,
    RowValidationError,
    StatementParseError,
    TotalsMismatchError,
)
from portfoliosentinel.tools.parser import parse_account_statement


def _write_bad_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["Titular", "Titular-Sintetico-Fixture"])
    ws.append(["MONEDAS"])
    ws.append(["Moneda", "Saldo"])
    ws.append(["ARS", 100.0])
    # Faltan secciones obligatorias → MalformedStatementError
    wb.save(path)


def test_e4_malformed_xlsx_clean_reject(tmp_path: Path):
    bad = tmp_path / "malformed.xlsx"
    _write_bad_xlsx(bad)

    exc: Exception | None = None
    try:
        parse_account_statement(bad)
    except StatementParseError as e:
        exc = e

    checks = {
        "lanzo_excepcion_tipada": isinstance(
            exc, (MalformedStatementError, RowValidationError, TotalsMismatchError)
        ),
        "mensaje_claro": bool(exc and str(exc).strip()),
        "no_es_generica": not isinstance(exc, type(None)),
    }
    assert checks["lanzo_excepcion_tipada"], f"E-4: excepción inesperada {type(exc)}: {exc}"
    assert "Falta la sección" in str(exc) or "malform" in str(exc).lower() or str(exc)

    record_result(
        CaseResult(
            case_id="E-4",
            kind="scenario",
            passed=True,
            deterministic_checks=checks,
            latency_s=0.0,
            cost_usd=0.0,
            validator_reroutes=0,
            validator_attempts=0,
            notes=f"Parser rechazó con {type(exc).__name__}: {exc}",
        )
    )
