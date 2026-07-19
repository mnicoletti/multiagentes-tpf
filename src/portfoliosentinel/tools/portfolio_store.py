"""Cliente in-process del portfolio-store-mcp (mismas operaciones que las tools FastMCP).

El server FastMCP (`mcp_servers.portfolio_store.server`) expone el contrato MCP;
el grafo usa este cliente contra la misma capa append-only (ADR-0003 / ADR-0005).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.config.settings import DEFAULT_DOMAIN_DB
from portfoliosentinel.tools.schemas import AccountSnapshot


def open_domain_store(db_path: str | Path | None = None) -> PortfolioStore:
    return PortfolioStore(db_path or DEFAULT_DOMAIN_DB)


def snapshot_to_store_dict(snapshot: AccountSnapshot) -> dict[str, Any]:
    return snapshot.model_dump(mode="json")


def snapshot_from_store_dict(data: dict[str, Any]) -> AccountSnapshot:
    return AccountSnapshot.model_validate(data)
