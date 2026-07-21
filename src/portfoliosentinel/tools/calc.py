"""Calculadora de rebalanceo — aritmética pura, sin LLM (ADR-0002)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from portfoliosentinel.tools.schemas import AccountSnapshot

# Cluster mínimo: evita acoplar tools → graph.state.
ClusterLike = Any  # objeto con .name, .driver, .tickers


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PlannedTrade(BaseModel):
    """Trade con cantidad tipada (entrada a la calculadora)."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: str  # sell | buy
    quantity: Decimal
    price_ars: Decimal | None = None  # si None, usa precio del snapshot

    @field_validator("quantity", "price_ars", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal | None:
        if v is None or v == "":
            return None
        return _as_decimal(v)  # type: ignore[arg-type]


class ClusterWeightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    driver: str
    tickers: list[str]
    total_ars: Decimal
    weight: Decimal

    @field_validator("total_ars", "weight", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class RebalanceCalcResult(BaseModel):
    """Salida determinista de la calculadora."""

    model_config = ConfigDict(extra="forbid")

    capital_freed_ars: Decimal
    capital_new_ars: Decimal
    capital_available_ars: Decimal
    capital_deployed_ars: Decimal
    cash_residual_ars: Decimal
    resulting_cluster_weights: list[ClusterWeightResult]
    resulting_position_totals: dict[str, Decimal] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @field_validator(
        "capital_freed_ars",
        "capital_new_ars",
        "capital_available_ars",
        "capital_deployed_ars",
        "cash_residual_ars",
        mode="before",
    )
    @classmethod
    def _coerce_caps(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


def _holding_map(snapshot: AccountSnapshot) -> dict[str, tuple[Decimal, Decimal, Decimal]]:
    """ticker → (qty, price, total)."""
    out: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    for p in snapshot.positions:
        out[p.ticker.upper()] = (p.quantity, p.price, p.total)
    return out


def compute_rebalance(
    snapshot: AccountSnapshot,
    trades: list[PlannedTrade],
    *,
    capital_new_ars: Decimal | None = None,
    clusters: list[ClusterLike] | None = None,
) -> RebalanceCalcResult:
    """Aplica ventas/compras sobre el snapshot y recalcula pesos por cluster.

    - Ventas liberan capital (qty * price).
    - Compras consumen capital disponible (liberado + capital nuevo).
    - Pesos resultantes: sobre total_ars del snapshot ajustado por cash residual.
    """
    holdings = _holding_map(snapshot)
    capital_new = _as_decimal(capital_new_ars or 0)
    position_totals: dict[str, Decimal] = {t: total for t, (_q, _p, total) in holdings.items()}
    position_qty: dict[str, Decimal] = {t: q for t, (q, _p, _tot) in holdings.items()}

    freed = Decimal("0")
    deployed = Decimal("0")
    notes: list[str] = []

    for trade in trades:
        ticker = trade.ticker.upper()
        qty = trade.quantity
        if qty <= 0:
            notes.append(f"trade ignorado qty<=0: {ticker}")
            continue

        if trade.side == "sell":
            if ticker not in holdings:
                notes.append(f"venta de ticker ausente en snapshot: {ticker}")
                continue
            hold_qty, hold_price, _ = holdings[ticker]
            price = trade.price_ars if trade.price_ars is not None else hold_price
            # No valida qty vs holding acá: eso es del validator. Truncamos aritmética.
            sell_qty = min(qty, position_qty.get(ticker, Decimal("0")))
            proceeds = sell_qty * price
            freed += proceeds
            position_qty[ticker] = position_qty.get(ticker, Decimal("0")) - sell_qty
            position_totals[ticker] = position_qty[ticker] * price
            if sell_qty < qty:
                notes.append(
                    f"venta {ticker}: qty pedida {qty} > tenencia; calculadora usó {sell_qty}"
                )
        elif trade.side == "buy":
            price = trade.price_ars
            if price is None:
                if ticker in holdings:
                    price = holdings[ticker][1]
                else:
                    notes.append(f"compra {ticker} sin precio: ignorada")
                    continue
            cost = qty * price
            deployed += cost
            position_qty[ticker] = position_qty.get(ticker, Decimal("0")) + qty
            position_totals[ticker] = position_qty[ticker] * price
        else:
            notes.append(f"side desconocido '{trade.side}' en {ticker}")

    available = freed + capital_new
    residual = available - deployed
    if residual < 0:
        notes.append(
            f"capital insuficiente: available={available} deployed={deployed} "
            f"(residual negativo={residual})"
        )

    # Total cartera resultante ≈ suma posiciones + cash ARS original + residual neto
    cash_ars = Decimal("0")
    for c in snapshot.cash:
        if c.currency == "ARS":
            cash_ars += c.amount
    # Tras liberar/desplegar: cash_ars + residual (residual ya incluye freed - deployed + new)
    # Pero freed salió de posiciones; capital_new entra; deployed vuelve a posiciones.
    # cash resultante = cash_ars + capital_new + freed - deployed = cash_ars + residual
    # donde residual = freed + capital_new - deployed.
    resulting_cash = cash_ars + residual
    positions_sum = sum(position_totals.values(), Decimal("0"))
    new_total = positions_sum + max(resulting_cash, Decimal("0"))

    cluster_results: list[ClusterWeightResult] = []
    if clusters:
        for cl in clusters:
            tickers_u = [t.upper() for t in cl.tickers]
            tot = sum((position_totals.get(t, Decimal("0")) for t in tickers_u), Decimal("0"))
            weight = (tot / new_total) if new_total > 0 else Decimal("0")
            cluster_results.append(
                ClusterWeightResult(
                    name=cl.name,
                    driver=cl.driver,
                    tickers=list(cl.tickers),
                    total_ars=tot,
                    weight=weight,
                )
            )

    return RebalanceCalcResult(
        capital_freed_ars=freed,
        capital_new_ars=capital_new,
        capital_available_ars=available,
        capital_deployed_ars=deployed,
        cash_residual_ars=residual,
        resulting_cluster_weights=cluster_results,
        resulting_position_totals={k: v for k, v in position_totals.items()},
        notes=notes,
    )


def trades_from_plan_actions(actions: list[Any]) -> list[PlannedTrade]:
    """Convierte acciones del plan (Pydantic o dict) a PlannedTrade para la calc."""
    trades: list[PlannedTrade] = []
    sell_actions = {"salir", "tomar_ganancia_parcial", "reducir"}
    buy_actions = {"comprar"}
    for raw in actions:
        if hasattr(raw, "model_dump"):
            a = raw.model_dump()
        else:
            a = dict(raw)
        action = str(a.get("action", "")).lower()
        ticker = str(a.get("ticker", "")).upper()
        qty = a.get("quantity")
        if qty is None:
            continue
        qty_d = _as_decimal(qty)
        if action in sell_actions:
            trades.append(PlannedTrade(ticker=ticker, side="sell", quantity=qty_d))
        elif action in buy_actions:
            trades.append(PlannedTrade(ticker=ticker, side="buy", quantity=qty_d))
    return trades
