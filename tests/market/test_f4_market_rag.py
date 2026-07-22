"""Tests F4: market-data fixture, MEP warning, Chroma retrieval, report indexing."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from mcp_servers.market_data.client import (
    get_fx_rates,
    get_quotes,
    network_call_count,
    reset_network_call_count,
)
from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.config.settings import DEFAULT_FIXTURE_XLSX, MEP_DIVERGENCE_THRESHOLD_PCT
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import RunInputs
from portfoliosentinel.rag.ingest import ingest_knowledge, ingest_report
from portfoliosentinel.rag.retriever import retrieve
from portfoliosentinel.tools.mep_check import check_mep_divergence, mep_mid_from_fx
from portfoliosentinel.tools.parser import parse_account_statement
from portfoliosentinel.tools.web_search import (
    network_call_count as web_network_call_count,
)
from portfoliosentinel.tools.web_search import (
    reset_network_call_count as reset_web_network_call_count,
)
from portfoliosentinel.tools.web_search import web_search

FIXTURE = DEFAULT_FIXTURE_XLSX
REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = REPO_ROOT / "knowledge"


def _initial_state(*, xlsx: str | None, run_id: str, **input_kw) -> dict:
    return {
        "run_id": run_id,
        "inputs": RunInputs(xlsx_path=xlsx, auto_confirm_constraints=True, **input_kw),
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


@pytest.fixture(autouse=True)
def _market_fixture_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARKET_FIXTURE", "1")
    reset_network_call_count()
    reset_web_network_call_count()


def test_fixture_mode_zero_external_http_except_unused():
    """DoD: MARKET_FIXTURE=1 → market-data y web_search no hacen HTTP."""
    assert os.environ.get("MARKET_FIXTURE") == "1"
    reset_network_call_count()
    reset_web_network_call_count()

    fx = get_fx_rates()
    quotes = get_quotes(["GGAL", "YPFD"])
    web = web_search("Dólar MEP Argentina")

    assert fx["source"] == "fixture"
    assert "mep" in fx["rates"]
    assert "GGAL" in quotes["quotes"]
    assert web["source"] == "fixture"
    assert network_call_count() == 0
    assert web_network_call_count() == 0


def test_planted_mep_divergence_triggers_warning():
    """DoD: divergencia MEP plantada en fixture → warning."""
    snapshot = parse_account_statement(FIXTURE)
    fx = get_fx_rates()
    mep_market = mep_mid_from_fx(fx)
    # Fixture plantada: mid=1450 vs implícito=1210
    assert mep_market == Decimal("1450.0") or mep_market == Decimal("1450")
    result = check_mep_divergence(snapshot.mep_implied, mep_market)
    assert result["exceeds_threshold"] is True
    assert result["mep_warning"] is not None
    assert "Divergencia de MEP" in result["mep_warning"]
    assert result["mep_divergence_pct"] > Decimal(str(MEP_DIVERGENCE_THRESHOLD_PCT))


def test_chroma_three_queries_return_correct_knowledge_docs(tmp_path: Path):
    """DoD: 3 queries de prueba → documento correcto de knowledge/."""
    chroma = tmp_path / "chroma"
    meta = ingest_knowledge(KNOWLEDGE, persist_dir=chroma)
    assert meta["count"] >= 8

    cases = [
        (
            "MACD cruce histograma señal EMA metodología técnica",
            "macd-metodologia",
        ),
        (
            "CEDEAR ratio conversión driver riesgo subyacente panel local",
            "cedears-argentina",
        ),
        (
            "stop loss trailing interrupt no inventar niveles gestión riesgo",
            "gestion-riesgo-stops",
        ),
    ]
    for query, expected_id in cases:
        hits = retrieve(query, collection="knowledge", n_results=3, persist_dir=chroma)
        assert hits, f"sin hits para query={query!r}"
        top_ids = [h["id"] for h in hits]
        assert expected_id in top_ids, (
            f"query={query!r}: esperado {expected_id} en top3, got {top_ids}"
        )


def test_persisted_report_stub_indexed_and_retrievable(tmp_path: Path):
    """DoD: informe-stub persistido queda indexado y recuperable por retrieval."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    chroma = tmp_path / "chroma"
    store = PortfolioStore(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        # Pre-ingesta knowledge para que mercado tenga corpus.
        ingest_knowledge(KNOWLEDGE, persist_dir=chroma)
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma,
            include_cartera=False,
            include_mercado=True,
            include_tecnico=False,
            include_planificador=False,
            mercado_skip_llm=True,
        )
        run_id = f"f4-{uuid.uuid4().hex[:8]}"
        # Marcador único en el run_id para retrieval.
        result = graph.invoke(
            _initial_state(xlsx=str(FIXTURE), run_id=run_id),
            config={"configurable": {"thread_id": run_id}},
        )
        assert result["report"] is not None
        assert "Informe stub" in result["report"]
        assert result.get("market_context") is not None
        assert result["market_context"].mep_warning is not None

        reports = store.list_reports()
        assert len(reports) == 1
        report_id = reports[0]["id"]

        hits = retrieve(
            f"Informe stub {run_id} Descargo restricciones",
            collection="reports",
            n_results=3,
            persist_dir=chroma,
        )
        assert hits, "informe no recuperable"
        assert any(h["id"] == report_id for h in hits)
        assert run_id in (hits[0]["document"] or "")
    finally:
        conn.close()
        store.close()


def test_full_run_fixture_mode_zero_market_http(tmp_path: Path):
    """DoD: corrida completa con MARKET_FIXTURE=1 sin HTTP de market/web (salvo LLM omitido)."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    chroma = tmp_path / "chroma"
    store = PortfolioStore(domain)
    checkpointer, conn = get_checkpointer(ck)
    reset_network_call_count()
    reset_web_network_call_count()
    try:
        ingest_knowledge(KNOWLEDGE, persist_dir=chroma)
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            chroma_dir=chroma,
            include_cartera=False,
            include_mercado=True,
            include_tecnico=False,
            include_planificador=False,
            mercado_skip_llm=True,
        )
        run_id = f"f4net-{uuid.uuid4().hex[:8]}"
        result = graph.invoke(
            _initial_state(xlsx=str(FIXTURE), run_id=run_id),
            config={"configurable": {"thread_id": run_id}},
        )
        assert result["market_context"] is not None
        assert result["market_context"].fx_rates is not None
        assert result["market_context"].fx_rates.get("source") == "fixture"
        assert network_call_count() == 0
        assert web_network_call_count() == 0
    finally:
        conn.close()
        store.close()


def test_ingest_report_direct_roundtrip(tmp_path: Path):
    chroma = tmp_path / "chroma"
    marker = f"UNIQUE_REPORT_MARKER_{uuid.uuid4().hex}"
    content = f"# Informe stub\n\n{marker}\n\nDescargo: no asesora."
    meta = ingest_report(
        report_id="rep-test-1",
        run_id="run-test-1",
        content_md=content,
        persist_dir=chroma,
    )
    assert meta["id"] == "rep-test-1"
    hits = retrieve(marker, collection="reports", n_results=1, persist_dir=chroma)
    assert hits and hits[0]["id"] == "rep-test-1"
    assert marker in hits[0]["document"]
