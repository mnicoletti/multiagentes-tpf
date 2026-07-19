"""Checkpointer SQLite — estado de ejecución por thread_id (ADR-0003)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from portfoliosentinel.config.settings import DEFAULT_CHECKPOINT_DB

# Tipos de dominio que el checkpointer debe poder (de)serializar (msgpack).
_ALLOWED_MSGPACK_MODULES: list[tuple[str, ...]] = [
    ("portfoliosentinel.graph.state", "RunInputs"),
    ("portfoliosentinel.graph.state", "Constraint"),
    ("portfoliosentinel.graph.state", "StalenessInfo"),
    ("portfoliosentinel.graph.state", "ClassWeight"),
    ("portfoliosentinel.graph.state", "PositionWeight"),
    ("portfoliosentinel.graph.state", "RiskCluster"),
    ("portfoliosentinel.graph.state", "Diagnosis"),
    ("portfoliosentinel.graph.state", "MarketContext"),
    ("portfoliosentinel.graph.state", "TechnicalReading"),
    ("portfoliosentinel.graph.state", "RebalancePlan"),
    ("portfoliosentinel.graph.state", "ValidationResult"),
    ("portfoliosentinel.graph.state", "ExternalReview"),
    ("portfoliosentinel.graph.state", "InfoGap"),
    ("portfoliosentinel.tools.schemas", "AccountSnapshot"),
    ("portfoliosentinel.tools.schemas", "CashBalance"),
    ("portfoliosentinel.tools.schemas", "Position"),
    ("decimal", "Decimal"),
    ("datetime", "date"),
    ("datetime", "datetime"),
]


def _serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def open_checkpointer(db_path: str | Path | None = None) -> Iterator[SqliteSaver]:
    """Abre un SqliteSaver listo para compilar el grafo.

    El caller mantiene el context manager abierto mientras use el grafo compilado.
    """
    path = Path(db_path) if db_path else DEFAULT_CHECKPOINT_DB
    conn = _connect(path)
    try:
        saver = SqliteSaver(conn, serde=_serde())
        saver.setup()
        yield saver
    finally:
        conn.close()


def get_checkpointer(db_path: str | Path | None = None) -> tuple[SqliteSaver, sqlite3.Connection]:
    """Factory sin context manager (CLI / tests que cierran a mano)."""
    path = Path(db_path) if db_path else DEFAULT_CHECKPOINT_DB
    conn = _connect(path)
    saver = SqliteSaver(conn, serde=_serde())
    saver.setup()
    return saver, conn
