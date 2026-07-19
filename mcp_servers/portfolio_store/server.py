"""FastMCP server: portfolio-store-mcp (SPEC §7.1, ADR-0005).

Tools: read_active_constraints, read_last_snapshot, write_snapshot,
write_report, list_reports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.portfolio_store.db import PortfolioStore

DEFAULT_DB = Path(
    os.environ.get(
        "PORTFOLIOSENTINEL_DOMAIN_DB",
        Path(__file__).resolve().parents[2] / "data" / "portfolio_store.sqlite",
    )
)

mcp = FastMCP("portfolio-store-mcp")
_store: PortfolioStore | None = None


def _get_store() -> PortfolioStore:
    global _store
    if _store is None:
        _store = PortfolioStore(DEFAULT_DB)
    return _store


@mcp.tool()
def read_active_constraints() -> str:
    """Lee las restricciones duras activas (último evento active por regla)."""
    rows = _get_store().read_active_constraints()
    return json.dumps(rows, ensure_ascii=False)


@mcp.tool()
def read_last_snapshot() -> str:
    """Lee el último snapshot de cartera persistido (o null si no hay)."""
    row = _get_store().read_last_snapshot()
    return json.dumps(row, ensure_ascii=False, default=str)


@mcp.tool()
def write_snapshot(data_json: str, source: str) -> str:
    """Persiste un snapshot nuevo (append-only). data_json = JSON del AccountSnapshot."""
    data: dict[str, Any] = json.loads(data_json)
    meta = _get_store().write_snapshot(data, source=source)
    return json.dumps(meta, ensure_ascii=False)


@mcp.tool()
def write_report(run_id: str, content_md: str) -> str:
    """Persiste un informe (append-only) asociado al run_id."""
    meta = _get_store().write_report(run_id=run_id, content_md=content_md)
    return json.dumps(meta, ensure_ascii=False)


@mcp.tool()
def list_reports() -> str:
    """Lista informes históricos ordenados por timestamp."""
    rows = _get_store().list_reports()
    return json.dumps(rows, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
