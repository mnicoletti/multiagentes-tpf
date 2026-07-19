"""Compilación del grafo F3: intake → orquestador → analista_cartera → persist."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.config.settings import DEFAULT_DOMAIN_DB
from portfoliosentinel.graph.nodes import (
    analista_cartera_node,
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
    interrupt_after: list[str] | None = None,
    include_cartera: bool = True,
) -> Any:
    """Construye y compila el grafo F3.

    `store` / `domain_db`: SQLite de dominio (≠ checkpointer).
    `include_cartera=False`: salta el LLM (tests DoD de persistencia).
    """
    domain_store = store or open_domain_store(domain_db or DEFAULT_DOMAIN_DB)

    def _intake(state: PortfolioState) -> dict:
        return intake_node(state, store=domain_store)

    def _orquestador(state: PortfolioState) -> dict:
        return orchestrator_node(state, store=domain_store)

    def _persist(state: PortfolioState) -> dict:
        return persist_node(state, store=domain_store)

    graph = StateGraph(PortfolioState)
    graph.add_node("intake", _intake)
    graph.add_node("orquestador", _orquestador)
    if include_cartera:
        graph.add_node("analista_cartera", analista_cartera_node)
    graph.add_node("persist", _persist)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "orquestador")
    if include_cartera:
        graph.add_edge("orquestador", "analista_cartera")
        graph.add_edge("analista_cartera", "persist")
    else:
        graph.add_edge("orquestador", "persist")
    graph.add_edge("persist", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after or [],
    )
