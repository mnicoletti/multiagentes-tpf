"""Compilación del grafo F4: intake → orquestador → cartera → mercado → persist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR, DEFAULT_DOMAIN_DB
from portfoliosentinel.graph.nodes import (
    analista_cartera_node,
    analista_mercado_node,
    intake_node,
    orchestrator_node,
    persist_node,
)
from portfoliosentinel.graph.state import PortfolioState
from portfoliosentinel.tools.portfolio_store import open_domain_store


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    store: PortfolioStore | None = None,
    domain_db: str | Path | None = None,
    chroma_dir: str | Path | None = None,
    interrupt_after: list[str] | None = None,
    include_cartera: bool = True,
    include_mercado: bool = True,
    mercado_skip_llm: bool = False,
) -> Any:
    """Construye y compila el grafo F4.

    `include_cartera` / `include_mercado`: omiten nodos LLM (tests DoD).
    `mercado_skip_llm=True`: nodo mercado determinista (FX/RAG/MEP) sin LLM.
    """
    domain_store = store or open_domain_store(domain_db or DEFAULT_DOMAIN_DB)
    chroma = Path(chroma_dir) if chroma_dir else DEFAULT_CHROMA_DIR

    def _intake(state: PortfolioState) -> dict:
        return intake_node(state, store=domain_store)

    def _orquestador(state: PortfolioState) -> dict:
        return orchestrator_node(state, store=domain_store)

    def _mercado(state: PortfolioState) -> dict:
        return analista_mercado_node(
            state,
            chroma_dir=chroma,
            skip_llm=mercado_skip_llm,
        )

    def _persist(state: PortfolioState) -> dict:
        return persist_node(state, store=domain_store, chroma_dir=chroma)

    graph = StateGraph(PortfolioState)
    graph.add_node("intake", _intake)
    graph.add_node("orquestador", _orquestador)
    if include_cartera:
        graph.add_node("analista_cartera", analista_cartera_node)
    if include_mercado:
        graph.add_node("analista_mercado", _mercado)
    graph.add_node("persist", _persist)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "orquestador")

    # Cadena lineal según nodos activos.
    prev = "orquestador"
    if include_cartera:
        graph.add_edge(prev, "analista_cartera")
        prev = "analista_cartera"
    if include_mercado:
        graph.add_edge(prev, "analista_mercado")
        prev = "analista_mercado"
    graph.add_edge(prev, "persist")
    graph.add_edge("persist", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after or [],
    )
