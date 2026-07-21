"""FastMCP server: market-data-mcp (SPEC §7.2, ADR-0005).

Tools: get_fx_rates, get_quotes.
Modo fixture obligatorio vía MARKET_FIXTURE=1.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.market_data.client import get_fx_rates as _get_fx_rates
from mcp_servers.market_data.client import get_quotes as _get_quotes
from mcp_servers.market_data.client import is_fixture_mode

mcp = FastMCP("market-data-mcp")


@mcp.tool()
def get_fx_rates() -> str:
    """Cotizaciones FX: MEP, CCL y oficial (dolarapi o fixture)."""
    return json.dumps(_get_fx_rates(), ensure_ascii=False)


@mcp.tool()
def get_quotes(tickers_csv: str = "") -> str:
    """Cotizaciones de panel local. tickers_csv: 'GGAL,YPFD' o vacío = todos (fixture)."""
    tickers = [t.strip() for t in tickers_csv.split(",") if t.strip()] or None
    return json.dumps(_get_quotes(tickers), ensure_ascii=False)


@mcp.tool()
def fixture_mode_status() -> str:
    """Indica si el server está sirviendo fixtures (sin red)."""
    return json.dumps({"fixture_mode": is_fixture_mode()}, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
