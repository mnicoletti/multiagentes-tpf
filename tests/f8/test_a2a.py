"""Tests F8 — A2A consultivo no bloqueante (ADR-0008)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from a2a_compliance.app import app
from a2a_compliance.rules import apply_compliance_rules
from portfoliosentinel.config.settings import DEFAULT_FIXTURE_XLSX, KNOWLEDGE_DIR
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import ExternalReview, RunInputs
from portfoliosentinel.rag.ingest import ingest_knowledge
from portfoliosentinel.tools.a2a_client import (
    UNAVAILABLE_MSG,
    format_a2a_section,
    review_plan_via_a2a,
)
from portfoliosentinel.tools.portfolio_store import open_domain_store

FIXTURE = DEFAULT_FIXTURE_XLSX


def _initial_state(**input_kw):
    run_id = input_kw.pop("run_id", f"f8-{uuid.uuid4().hex[:8]}")
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


def test_agent_card_has_review_plan_skill():
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"]
    assert card["url"].endswith("/a2a")
    skills = card["skills"]
    assert len(skills) == 1
    assert skills[0]["id"] == "review_plan"


def test_a2a_message_send_review_plan():
    client = TestClient(app)
    body = {
        "jsonrpc": "2.0",
        "id": "t1",
        "method": "message/send",
        "params": {
            "metadata": {
                "plan": {
                    "actions": [
                        {"ticker": "GGAL", "action": "reducir", "stop_level": None},
                    ],
                    "cluster_weights": [{"name": "bancos", "weight": "0.50"}],
                    "restricted_tickers": ["YPFD"],
                }
            }
        },
    }
    # Sin LLM en CI local del servicio.
    import os

    os.environ["A2A_SKIP_LLM"] = "1"
    resp = client.post("/a2a", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    task = data["result"]
    assert task["status"]["state"] == "completed"
    art = task["artifacts"][0]["parts"][0]["data"]
    assert art["skill"] == "review_plan"
    assert isinstance(art["observations"], list)
    assert art["observations"]  # concentración + stop faltante


def test_compliance_rules_cluster_and_restricted():
    obs = apply_compliance_rules(
        {
            "actions": [{"ticker": "YPFD", "action": "vender", "stop_level": "100"}],
            "cluster_weights": [{"name": "oil", "weight": "0.40"}],
            "restricted_tickers": ["YPFD"],
        }
    )
    assert any("YPFD" in o for o in obs)
    assert any("Concentración" in o for o in obs)


def test_client_degrades_when_service_down(monkeypatch):
    monkeypatch.setenv("A2A_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("A2A_TIMEOUT_S", "0.2")
    review = review_plan_via_a2a(None)
    assert review.available is False
    assert UNAVAILABLE_MSG in review.observations[0]
    section = format_a2a_section(review)
    assert UNAVAILABLE_MSG in section


def test_graph_continues_when_a2a_down(tmp_path: Path, monkeypatch):
    """DoD F8: apagar A2A → el grafo sigue y el informe marca no disponible."""
    monkeypatch.setenv("MARKET_FIXTURE", "1")
    monkeypatch.setenv("A2A_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("A2A_TIMEOUT_S", "0.2")

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
        thread_id = f"f8-down-{uuid.uuid4().hex[:8]}"
        result = graph.invoke(
            _initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                new_constraints_text="no vender YPFD",
                capital_new_ars=Decimal("100000"),
            ),
            config={"configurable": {"thread_id": thread_id}},
        )
        review = result.get("a2a_review")
        assert isinstance(review, ExternalReview)
        assert review.available is False
        assert UNAVAILABLE_MSG in (review.observations or [""])[0]
        report = result.get("report")
        assert report is not None
        assert UNAVAILABLE_MSG in report
        assert "## 1. Encabezado" in report
    finally:
        conn.close()
        store.close()


def test_graph_with_live_a2a_app(tmp_path: Path, monkeypatch):
    """Con TestClient: review disponible y sección anexada al informe."""
    monkeypatch.setenv("MARKET_FIXTURE", "1")
    monkeypatch.setenv("A2A_SKIP_LLM", "1")

    client = TestClient(app)

    def _fake_review(plan, *, constraints=None, diagnosis=None, timeout_s=None):
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "message/send",
            "params": {
                "metadata": {
                    "plan": {
                        "actions": [],
                        "cluster_weights": [],
                        "restricted_tickers": [],
                    }
                }
            },
        }
        resp = client.post("/a2a", json=payload)
        data = resp.json()["result"]
        art = data["artifacts"][0]["parts"][0]["data"]
        return ExternalReview(
            available=True,
            approved=bool(art.get("approved")),
            observations=list(art.get("observations") or []),
            summary="ok",
        )

    monkeypatch.setattr(
        "portfoliosentinel.tools.a2a_client.review_plan_via_a2a",
        _fake_review,
    )

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
        thread_id = f"f8-up-{uuid.uuid4().hex[:8]}"
        result = graph.invoke(
            _initial_state(
                run_id=thread_id,
                xlsx_path=str(FIXTURE),
                capital_new_ars=Decimal("100000"),
            ),
            config={"configurable": {"thread_id": thread_id}},
        )
        review = result.get("a2a_review")
        assert review is not None and review.available is True
        assert result.get("report")
        assert "## Revisión externa (A2A)" in result["report"]
    finally:
        conn.close()
        store.close()
