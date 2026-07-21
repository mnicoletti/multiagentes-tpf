"""Cliente de market-data: modo fixture (disco) o live (dolarapi / panel).

Con MARKET_FIXTURE=1 nunca toca red. Contador `_network_calls` para DoD/tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Contador de llamadas HTTP reales (live). En fixture mode debe permanecer en 0.
_network_calls: int = 0

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_DIR = REPO_ROOT / "fixtures" / "market"

DOLARAPI_BASE = "https://dolarapi.com/v1/dolares"
# Panel local simplificado (live). En demo/evals siempre se usa fixture.
PANEL_QUOTES_URL = "https://data912.com/live/arg_stocks"


def is_fixture_mode() -> bool:
    return os.environ.get("MARKET_FIXTURE", "0").lower() in {"1", "true", "yes"}


def reset_network_call_count() -> None:
    global _network_calls
    _network_calls = 0


def network_call_count() -> int:
    return _network_calls


def _fixture_dir() -> Path:
    raw = os.environ.get("MARKET_FIXTURE_DIR")
    return Path(raw) if raw else DEFAULT_FIXTURE_DIR


def _load_json(name: str) -> dict[str, Any]:
    path = _fixture_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"Fixture de market-data no encontrada: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _http_get_json(url: str) -> Any:
    global _network_calls
    _network_calls += 1
    import httpx  # lazy: solo en live

    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def _dolarapi_to_rate(payload: dict[str, Any]) -> dict[str, float]:
    compra = float(payload["compra"])
    venta = float(payload["venta"])
    return {"compra": compra, "venta": venta, "mid": (compra + venta) / 2.0}


def get_fx_rates() -> dict[str, Any]:
    """MEP / CCL / oficial. Fixture o dolarapi."""
    if is_fixture_mode():
        data = _load_json("fx_rates.json")
        data = dict(data)
        data["source"] = "fixture"
        return data

    mep = _http_get_json(f"{DOLARAPI_BASE}/bolsa")
    ccl = _http_get_json(f"{DOLARAPI_BASE}/contadoconliqui")
    oficial = _http_get_json(f"{DOLARAPI_BASE}/oficial")
    return {
        "as_of": mep.get("fechaActualizacion"),
        "source": "dolarapi",
        "rates": {
            "mep": _dolarapi_to_rate(mep),
            "ccl": _dolarapi_to_rate(ccl),
            "oficial": _dolarapi_to_rate(oficial),
        },
    }


def get_quotes(tickers: list[str] | None = None) -> dict[str, Any]:
    """Cotizaciones de panel local para los tickers pedidos (o todos en fixture)."""
    wanted = [t.upper() for t in tickers] if tickers else None

    if is_fixture_mode():
        data = _load_json("quotes.json")
        quotes: dict[str, Any] = dict(data.get("quotes") or {})
        if wanted is not None:
            quotes = {k: v for k, v in quotes.items() if k.upper() in wanted}
        return {
            "as_of": data.get("as_of"),
            "source": "fixture",
            "currency": data.get("currency", "ARS"),
            "quotes": quotes,
        }

    raw = _http_get_json(PANEL_QUOTES_URL)
    # data912 suele devolver lista de {symbol, ...} o dict; normalizamos.
    parsed: dict[str, Any] = {}
    items = raw if isinstance(raw, list) else raw.get("data") or raw.get("quotes") or []
    if isinstance(items, dict):
        items = [{"symbol": k, **v} for k, v in items.items()]
    for item in items:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or item.get("ticker") or "").upper()
        if not sym:
            continue
        if wanted is not None and sym not in wanted:
            continue
        last = item.get("c") or item.get("last") or item.get("price") or item.get("q_bid")
        if last is None:
            continue
        parsed[sym] = {
            "last": float(last),
            "bid": float(item["bid"]) if item.get("bid") is not None else None,
            "ask": float(item["ask"]) if item.get("ask") is not None else None,
            "change_pct": item.get("pct_change") or item.get("change_pct"),
        }
    return {
        "as_of": None,
        "source": "data912",
        "currency": "ARS",
        "quotes": parsed,
    }
