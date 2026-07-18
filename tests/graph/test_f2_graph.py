"""Tests F2: pesos deterministas, estado y checkpoint sin LLM."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from portfoliosentinel.config.settings import DEFAULT_FIXTURE_XLSX
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import RunInputs
from portfoliosentinel.graph.weights import (
    cluster_coverage_gaps,
    compute_class_weights,
    compute_position_weights,
    materialize_clusters,
)
from portfoliosentinel.tools.parser import parse_account_statement
from tests.parser import expected as exp

FIXTURE = DEFAULT_FIXTURE_XLSX


@pytest.fixture(scope="module")
def snapshot():
    assert FIXTURE.is_file(), f"Falta fixture {FIXTURE}"
    return parse_account_statement(FIXTURE)


def test_class_weights_sum_to_one(snapshot):
    weights = compute_class_weights(snapshot)
    total_ars = sum((w.total_ars for w in weights), Decimal("0"))
    assert total_ars == snapshot.total_ars
    total_w = sum((w.weight for w in weights), Decimal("0"))
    assert abs(total_w - Decimal("1")) < Decimal("1e-12")
    by_name = {w.asset_class: w for w in weights}
    assert by_name["ACCIONES"].total_ars == Decimal("18500000.00")
    assert by_name["BONOS"].total_ars == Decimal("2300000.00")
    assert by_name["CEDEARS"].total_ars == Decimal("1400000.00")
    assert by_name["CASH_ARS"].total_ars == Decimal("2000000.00")


def test_ggal_planted_concentration(snapshot):
    pos = compute_position_weights(snapshot)
    ggal = next(p for p in pos if p.ticker == "GGAL")
    assert ggal.weight == Decimal("16000000.00") / exp.TOTAL_ARS


def test_sovereign_cluster_weight_deterministic(snapshot):
    clusters = materialize_clusters(
        snapshot,
        [("soberano HD", "riesgo soberano hard-dollar", ["AL30", "GD30"])],
    )
    assert len(clusters) == 1
    assert clusters[0].tickers == ["AL30", "GD30"]
    assert clusters[0].total_ars == Decimal("2300000.00")
    assert clusters[0].weight == Decimal("2300000.00") / exp.TOTAL_ARS


def test_cluster_coverage_complete_with_vist_and_spy(snapshot):
    """VIST→energía y SPY→índice USA: cobertura total del caso plantado."""
    assignments = [
        ("banca", "bancario local", ["GGAL"]),
        ("energía", "energía argentina", ["YPFD", "VIST"]),
        ("soberano HD", "hard-dollar", ["AL30", "GD30"]),
        ("tech USA", "tech large-cap", ["AAPL"]),
        ("consumo LatAm", "marketplace", ["MELI"]),
        ("índice USA", "equity index S&P 500", ["SPY"]),
    ]
    assert cluster_coverage_gaps(snapshot, assignments) == set()
    clusters = materialize_clusters(snapshot, assignments)
    energy = next(c for c in clusters if "VIST" in c.tickers)
    assert "YPFD" in energy.tickers
    assert energy.total_ars == Decimal("2600000.00")
    spy_cluster = next(c for c in clusters if "SPY" in c.tickers)
    assert spy_cluster.tickers == ["SPY"]
    assert spy_cluster.total_ars == Decimal("100000.00")


def test_cluster_coverage_gaps_detects_omitted_tickers(snapshot):
    """Omisiones típicas (VIST/MELI) y lista vacía → gaps; SPY cubierto aparte."""
    assignments = [
        ("banca", "bancario local", ["GGAL"]),
        ("energía", "energía argentina", ["YPFD"]),
        ("soberano HD", "hard-dollar", ["AL30", "GD30"]),
        ("tech USA", "tech large-cap", ["AAPL"]),
        ("índice USA", "equity index", ["SPY"]),
        ("consumo LatAm", "marketplace", []),  # vacío
    ]
    assert cluster_coverage_gaps(snapshot, assignments) == {"VIST", "MELI"}
    clusters = materialize_clusters(snapshot, assignments, drop_empty=True)
    assert all(c.tickers for c in clusters)
    assert not any(c.name == "consumo LatAm" for c in clusters)


def test_checkpoint_after_parser(tmp_path: Path, snapshot):
    """Sin LLM: interrupt tras parser y re-inspección por thread_id."""
    db = tmp_path / "ck.sqlite"
    thread_id = f"test-{uuid.uuid4()}"
    checkpointer, conn = get_checkpointer(db)
    try:
        graph = build_graph(checkpointer=checkpointer, interrupt_after=["parser"])
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(
            {
                "run_id": thread_id,
                "inputs": RunInputs(xlsx_path=str(FIXTURE)),
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
            },
            config=config,
        )
        assert result["snapshot"] is not None
        assert result["diagnosis"] is None
        assert result["snapshot"].mep_implied == snapshot.mep_implied

        state = graph.get_state(config)
        assert state.values["snapshot"].total_ars == exp.TOTAL_ARS
        assert "orquestador" in state.next
    finally:
        conn.close()
