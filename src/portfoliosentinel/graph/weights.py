"""Pesos y concentraciones — aritmética pura sobre el snapshot (ADR-0002)."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from portfoliosentinel.graph.state import ClassWeight, PositionWeight, RiskCluster, Snapshot


def compute_class_weights(snapshot: Snapshot) -> list[ClassWeight]:
    """Pesos por clase contable + cash ARS, sobre total_ars."""
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for pos in snapshot.positions:
        totals[pos.asset_class] += pos.total
    cash_ars = next(c.amount for c in snapshot.cash if c.currency == "ARS")
    totals["CASH_ARS"] = cash_ars

    total = snapshot.total_ars
    weights: list[ClassWeight] = []
    for asset_class in ("ACCIONES", "BONOS", "CEDEARS", "CASH_ARS"):
        amount = totals.get(asset_class, Decimal("0"))
        weights.append(
            ClassWeight(
                asset_class=asset_class,
                total_ars=amount,
                weight=(amount / total) if total else Decimal("0"),
            )
        )
    return weights


def compute_position_weights(snapshot: Snapshot) -> list[PositionWeight]:
    total = snapshot.total_ars
    return [
        PositionWeight(
            ticker=pos.ticker,
            asset_class=pos.asset_class,
            total_ars=pos.total,
            weight=(pos.total / total) if total else Decimal("0"),
        )
        for pos in snapshot.positions
    ]


def _normalize_assignment_tickers(
    snapshot: Snapshot,
    tickers: list[str],
) -> list[str]:
    by_ticker = {p.ticker.upper(): p for p in snapshot.positions}
    uniq: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        t = raw.upper().strip()
        if not t or t in seen:
            continue
        if t not in by_ticker:
            continue
        seen.add(t)
        uniq.append(t)
    return uniq


def cluster_coverage_gaps(
    snapshot: Snapshot,
    assignments: list[tuple[str, str, list[str]]],
) -> set[str]:
    """Tickers del snapshot que no quedaron asignados a ningún cluster válido."""
    expected = {p.ticker.upper() for p in snapshot.positions}
    assigned: set[str] = set()
    for _name, _driver, tickers in assignments:
        assigned.update(_normalize_assignment_tickers(snapshot, tickers))
    return expected - assigned


def materialize_clusters(
    snapshot: Snapshot,
    assignments: list[tuple[str, str, list[str]]],
    *,
    drop_empty: bool = True,
) -> list[RiskCluster]:
    """Dado (name, driver, tickers) del LLM, calcula total_ars y weight deterministas."""
    by_ticker = {p.ticker.upper(): p for p in snapshot.positions}
    total = snapshot.total_ars
    clusters: list[RiskCluster] = []
    for name, driver, tickers in assignments:
        uniq = _normalize_assignment_tickers(snapshot, tickers)
        if drop_empty and not uniq:
            continue
        cluster_total = sum((by_ticker[t].total for t in uniq), Decimal("0"))
        clusters.append(
            RiskCluster(
                name=name,
                driver=driver,
                tickers=uniq,
                total_ars=cluster_total,
                weight=(cluster_total / total) if total else Decimal("0"),
            )
        )
    return clusters
