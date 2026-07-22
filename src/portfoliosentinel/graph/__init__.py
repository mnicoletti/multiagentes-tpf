"""Grafo LangGraph de PortfolioSentinel."""

from portfoliosentinel.graph.checkpointer import get_checkpointer, open_checkpointer
from portfoliosentinel.graph.state import (
    Constraint,
    Diagnosis,
    ExternalReview,
    InfoGap,
    MarketContext,
    PortfolioState,
    RebalancePlan,
    RunInputs,
    Snapshot,
    StalenessInfo,
    TechnicalReading,
    ValidationResult,
)

__all__ = [
    "Constraint",
    "Diagnosis",
    "ExternalReview",
    "InfoGap",
    "MarketContext",
    "PortfolioState",
    "RebalancePlan",
    "RunInputs",
    "Snapshot",
    "StalenessInfo",
    "TechnicalReading",
    "ValidationResult",
    "build_graph",
    "get_checkpointer",
    "open_checkpointer",
]


def __getattr__(name: str):
    if name == "build_graph":
        from portfoliosentinel.graph.builder import build_graph

        return build_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
