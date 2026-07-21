"""Compilación del grafo F5: cartera → mercado → técnico → plan → validator → HITL → persist."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
from portfoliosentinel.graph.nodes_f5 import (
    analista_tecnico_node,
    gaps_interrupt_node,
    planificador_node,
    route_after_validator,
    validation_escalate_node,
    validator_node,
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
    include_tecnico: bool = True,
    include_planificador: bool = True,
    mercado_skip_llm: bool = False,
    tecnico_skip_llm: bool = False,
    planificador_skip_llm: bool = False,
) -> Any:
    """Construye y compila el grafo F5.

    Flags `*_skip_llm` / `include_*` permiten DoD sin llamar proveedores.
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

    def _tecnico(state: PortfolioState) -> dict:
        return analista_tecnico_node(
            state,
            chroma_dir=chroma,
            skip_llm=tecnico_skip_llm,
        )

    def _planificador(state: PortfolioState) -> dict:
        return planificador_node(state, skip_llm=planificador_skip_llm)

    def _persist(state: PortfolioState) -> dict:
        return persist_node(state, store=domain_store, chroma_dir=chroma)

    graph = StateGraph(PortfolioState)
    graph.add_node("intake", _intake)
    graph.add_node("orquestador", _orquestador)

    if include_cartera:
        graph.add_node("analista_cartera", analista_cartera_node)
    if include_mercado:
        graph.add_node("analista_mercado", _mercado)
    if include_tecnico:
        graph.add_node("analista_tecnico", _tecnico)
    if include_planificador:
        graph.add_node("planificador", _planificador)
        graph.add_node("validator", validator_node)
        graph.add_node("validation_escalate", validation_escalate_node)
        graph.add_node("gaps_interrupt", gaps_interrupt_node)

    graph.add_node("persist", _persist)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "orquestador")

    # Cadena analítica hasta el join previo al planificador.
    analysis_nodes: list[str] = []
    prev = "orquestador"
    if include_cartera:
        graph.add_edge(prev, "analista_cartera")
        prev = "analista_cartera"

    if include_mercado and include_tecnico:
        # Secuencial (no fan-out paralelo): chromadb PersistentClient no es
        # thread-safe ante dos opens concurrentes (crash RustBindingsAPI).
        # Orden: mercado → técnico → planificador. Equivalente funcional a
        # SPEC §4.3 sin carrera sobre el store embebido.
        graph.add_edge(prev, "analista_mercado")
        graph.add_edge("analista_mercado", "analista_tecnico")
        analysis_nodes = ["analista_tecnico"]
        prev = "analista_tecnico"
    elif include_mercado:
        graph.add_edge(prev, "analista_mercado")
        analysis_nodes = ["analista_mercado"]
        prev = "analista_mercado"
    elif include_tecnico:
        graph.add_edge(prev, "analista_tecnico")
        analysis_nodes = ["analista_tecnico"]
        prev = "analista_tecnico"

    if include_planificador:
        if analysis_nodes:
            for n in analysis_nodes:
                graph.add_edge(n, "planificador")
        else:
            graph.add_edge(prev, "planificador")

        graph.add_edge("planificador", "validator")
        graph.add_conditional_edges(
            "validator",
            route_after_validator,
            {
                "planificador": "planificador",
                "validation_escalate": "validation_escalate",
                "gaps_interrupt": "gaps_interrupt",
                "persist": "persist",
            },
        )
        # Tras escalate HITL → persist
        graph.add_edge("validation_escalate", "persist")
        # Tras aportar gráficos: técnico → planificador (reloop validator)
        if include_tecnico:
            graph.add_edge("gaps_interrupt", "analista_tecnico")
        else:
            graph.add_edge("gaps_interrupt", "planificador")
    else:
        # Sin planificador (compat F4 tests): último análisis → persist
        if analysis_nodes:
            for n in analysis_nodes:
                graph.add_edge(n, "persist")
        else:
            graph.add_edge(prev, "persist")

    graph.add_edge("persist", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after or [],
    )


# Re-export tipado para callers
RouteName = Literal["planificador", "validation_escalate", "gaps_interrupt", "persist"]
