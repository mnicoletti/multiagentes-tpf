"""Compilación del grafo mínimo F2 (parser → orquestador → analista_cartera)."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from portfoliosentinel.graph.nodes import analista_cartera_node, orchestrator_node, parser_node
from portfoliosentinel.graph.state import PortfolioState


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    interrupt_after: list[str] | None = None,
) -> Any:
    """Construye y compila el grafo F2.

    Si se pasa checkpointer, la corrida es reanudable/inspeccionable por thread_id.
    `interrupt_after` permite pausar tras un nodo (útil para demos de checkpoint).
    """
    graph = StateGraph(PortfolioState)
    graph.add_node("parser", parser_node)
    graph.add_node("orquestador", orchestrator_node)
    graph.add_node("analista_cartera", analista_cartera_node)

    graph.add_edge(START, "parser")
    graph.add_edge("parser", "orquestador")
    graph.add_edge("orquestador", "analista_cartera")
    graph.add_edge("analista_cartera", END)

    return graph.compile(
        checkpointer=checkpointer,
        interrupt_after=interrupt_after or [],
    )
