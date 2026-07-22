#!/usr/bin/env python3
"""Genera fixtures/estadocuenta-broker-layout.xlsx (sintético, sin PII real).

Reproduce el layout ancho típico de export de bróker AR para tests del parser
multi-layout. Números inventados; titular/comitente ficticios.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "fixtures" / "estadocuenta-broker-layout.xlsx"

# Cash: ARS nativo + dos líneas USD (se agregan).
CASH_ARS = Decimal("100000.00")
USD_LINE_1 = Decimal("50.00")
USD_LINE_2 = Decimal("25.00")
CASH_USD = USD_LINE_1 + USD_LINE_2  # 75
MEP = Decimal("1500")

# Valor corriente cash (USD convertido a ARS + pesos).
CASH_VALOR = CASH_ARS + CASH_USD * MEP  # 100000 + 112500 = 212500

POSITIONS: list[tuple[str, str, Decimal, Decimal, Decimal]] = [
    ("ACCIONES", "BMA", Decimal("10"), Decimal("1000"), Decimal("10000")),
    ("ACCIONES", "TGNO4", Decimal("4"), Decimal("2500.5"), Decimal("10002")),
    ("BONOS", "GD35", Decimal("100"), Decimal("1200"), Decimal("120000")),
    ("CEDEARS", "NVDA", Decimal("5"), Decimal("15000"), Decimal("75000")),
    ("CEDEARS", "QQQ", Decimal("2"), Decimal("50000"), Decimal("100000")),
]

POS_SUM = sum((t for *_, t in POSITIONS), Decimal("0"))
TOTAL_ARS = CASH_VALOR + POS_SUM  # 212500 + 315002 = 527502
TOTAL_USD = Decimal("400")  # declarado (cartera expresada en USD)


def build(path: Path = OUT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Estado de Cuenta al 15-07-2026"

    ws.append(["ESTADO DE CUENTA"])
    ws.append([])
    ws.append(["TITULAR", None, "FECHA"])
    ws.append(["Titular-Sintetico-Broker", None, "15/07/2026"])
    ws.append(["COMITENTE"])
    ws.append(["COMITENTE-FICTICIO-BROKER-001"])
    ws.append([])
    ws.append(["TOTAL CARTERA EXPRESADO EN PESOS $", None, float(TOTAL_ARS)])
    ws.append(["TOTAL USD EXPRESADO EN DOLARES U$D", None, float(TOTAL_USD)])
    ws.append([])
    ws.append(["POR TIPO DE ACTIVO"])
    ws.append([])

    ws.append(["MONEDAS"])
    ws.append(
        ["MONEDA", "DESCRIPCIÓN", "CANT. DISPONIBLE", "PRECIO", "VALOR CORRIENTE", "% CARTERA"]
    )
    ws.append(
        [
            "USD",
            "CV7000 - DIVISA OPERABLES",
            float(USD_LINE_1),
            float(MEP),
            float(USD_LINE_1 * MEP),
            0.1,
        ]
    )
    ws.append(
        [
            "USD",
            "CV10000 - BILLETE",
            float(USD_LINE_2),
            float(MEP),
            float(USD_LINE_2 * MEP),
            0.05,
        ]
    )
    ws.append(["$", "Peso", float(CASH_ARS), 1, float(CASH_ARS), 0.2])
    ws.append(["SUBTOTAL", None, None, None, float(CASH_VALOR), 0.35])
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
        ws.append(
            [
                "ESPECIE",
                "DESCRIPCIÓN",
                "CANT. DISPONIBLE",
                "CANT. GARANTÍA",
                "PRECIO",
                "VALOR MONEDA COTIZACIÓN",
                "VALOR CORRIENTE",
                "% CARTERA",
            ]
        )
        class_sum = Decimal("0")
        for ticker, qty, price, total in by_class[asset_class]:
            class_sum += total
            ws.append(
                [
                    ticker,
                    f"Desc {ticker}",
                    float(qty),
                    0,
                    float(price),
                    float(total),
                    float(total),
                    0.1,
                ]
            )
        ws.append(["SUBTOTAL", None, None, None, None, None, float(class_sum), 0.1])
        ws.append([])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    out = build()
    print(f"Wrote {out}")
