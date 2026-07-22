"""Tests del post-proceso GC-2 (riesgo + mitigación en restringidos)."""

from __future__ import annotations

from decimal import Decimal

from portfoliosentinel.graph.f5_logic import enrich_restricted_mitigations
from portfoliosentinel.graph.state import Constraint, PlanAction
from portfoliosentinel.tools.parser import parse_account_statement
from portfoliosentinel.tools.schemas import AccountSnapshot

FIXTURE = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "fixtures"
    / "estadocuenta-sintetico.xlsx"
)


def _snap() -> AccountSnapshot:
    return parse_account_statement(FIXTURE)


def test_enrich_fills_ypfd_risk_and_vist_sell():
    snap = _snap()
    constraints = [
        Constraint(rule="no vender YPFD", ticker="YPFD", status="active", source="run")
    ]
    actions = [
        PlanAction(ticker="YPFD", action="mantener", rationale="ok"),
        PlanAction(ticker="VIST", action="mantener", rationale="olvidó mitigar"),
        PlanAction(ticker="GGAL", action="mantener"),
    ]
    out = enrich_restricted_mitigations(actions, snapshot=snap, constraints=constraints)
    ypfd = next(a for a in out if a.ticker == "YPFD")
    vist = next(a for a in out if a.ticker == "VIST")
    assert ypfd.action == "mantener"
    assert ypfd.risk_notes
    assert ypfd.mitigations
    assert vist.action in {"salir", "reducir", "tomar_ganancia_parcial"}
    assert vist.quantity is not None and vist.quantity > Decimal("0")


def test_enrich_noop_without_restrictions():
    snap = _snap()
    actions = [PlanAction(ticker="GGAL", action="mantener")]
    out = enrich_restricted_mitigations(actions, snapshot=snap, constraints=[])
    assert out == actions
