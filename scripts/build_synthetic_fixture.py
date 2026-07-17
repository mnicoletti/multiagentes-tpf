#!/usr/bin/env python3
"""Genera fixtures/estadocuenta-sintetico.xlsx (solo datos sintéticos, sin PII real)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "fixtures" / "estadocuenta-sintetico.xlsx"

# Valores canónicos — espejo de tests/parser/expected.py
CASH_ARS = Decimal("2000000.00")
CASH_USD = Decimal("3000.00")

# GGAL plantado sobreconcentrado (~66.7% del total ARS de cartera).
POSITIONS: list[tuple[str, str, Decimal, Decimal, Decimal]] = [
    # asset_class, ticker, qty, price, total
    ("ACCIONES", "GGAL", Decimal("2500"), Decimal("6400.00"), Decimal("16000000.00")),
    ("ACCIONES", "YPFD", Decimal("100"), Decimal("25000.00"), Decimal("2500000.00")),
    ("BONOS", "AL30", Decimal("200"), Decimal("7500.00"), Decimal("1500000.00")),
    ("BONOS", "GD30", Decimal("100"), Decimal("8000.00"), Decimal("800000.00")),
    ("CEDEARS", "AAPL", Decimal("30"), Decimal("20000.00"), Decimal("600000.00")),
    ("CEDEARS", "MELI", Decimal("20"), Decimal("30000.00"), Decimal("600000.00")),
]

TOTAL_ARS = Decimal("24000000.00")  # cash ARS + sum posiciones
TOTAL_USD = Decimal("20000.00")
# MEP implícito = 24000000 / 20000 = 1200 exacto


def build(path: Path = OUT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "EstadoCuenta"

    # Encabezado: etiquetas sintéticas (no PII real). El parser scrubbea a INV-001.
    ws.append(["Titular", "Titular-Sintetico-Fixture"])
    ws.append(["Comitente", "COMITENTE-FICTICIO-000"])
    ws.append(["Fecha", "2026-07-15"])
    ws.append([])

    ws.append(["MONEDAS"])
    ws.append(["Moneda", "Saldo"])
    ws.append(["ARS", float(CASH_ARS)])
    ws.append(["USD", float(CASH_USD)])
    ws.append([])

    by_class: dict[str, list[tuple[str, Decimal, Decimal, Decimal]]] = {
        "ACCIONES": [],
        "BONOS": [],
        "CEDEARS": [],
    }
    for asset_class, ticker, qty, price, total in POSITIONS:
        by_class[asset_class].append((ticker, qty, price, total))

    for asset_class in ("ACCIONES", "BONOS", "CEDEARS"):
        ws.append([asset_class])
        ws.append(["Ticker", "Cantidad", "Precio", "Total"])
        for ticker, qty, price, total in by_class[asset_class]:
            ws.append([ticker, float(qty), float(price), float(total)])
        ws.append([])

    ws.append(["TOTALES"])
    ws.append(["Total ARS", float(TOTAL_ARS)])
    ws.append(["Total USD", float(TOTAL_USD)])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    out = build()
    print(f"Fixture escrita en {out}")
