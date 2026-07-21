#!/usr/bin/env python3
"""Genera fixtures de imágenes sintéticas (panel FCI + gráficos trading). Sin PII."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "fixtures" / "images"


def _font(size: int = 18):
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _draw_line_chart(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    *,
    color: str = "#1a73e8",
    width: int = 3,
) -> None:
    if len(points) >= 2:
        draw.line(points, fill=color, width=width)


def build_fci_panel(path: Path) -> None:
    img = Image.new("RGB", (720, 420), "#0f172a")
    d = ImageDraw.Draw(img)
    font = _font(20)
    small = _font(14)
    d.text((24, 20), "FCI Liquidez Plus — panel sintético (INV-001)", fill="#e2e8f0", font=font)
    d.text((24, 56), "Propósito: tenencia_externa_fci (lo declara el usuario)", fill="#94a3b8", font=small)
    d.text((24, 90), "Patrimonio: $ 1.250.000 ARS", fill="#f8fafc", font=small)
    d.text((24, 115), "Rend. 30d: +1.8%   90d: +4.2%   YTD: +12.1%", fill="#86efac", font=small)
    d.text((24, 145), "Rol: liquidez-vs-retorno (curva suave)", fill="#cbd5e1", font=small)
    # Curva de patrimonio
    pts = [(60 + i * 40, 360 - int(40 + i * 8 + (i % 3) * 5)) for i in range(15)]
    _draw_line_chart(d, pts, color="#38bdf8")
    d.text((24, 380), "FIXTURE SINTÉTICA — no es un FCI real", fill="#64748b", font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def build_trading_chart(
    path: Path,
    *,
    ticker: str,
    title_extra: str,
    trend: str,
    show_stop_zone: bool,
) -> None:
    img = Image.new("RGB", (720, 420), "#111827")
    d = ImageDraw.Draw(img)
    font = _font(20)
    small = _font(14)
    d.text((24, 16), f"{ticker} — gráfico sintético", fill="#f9fafb", font=font)
    d.text((24, 48), title_extra, fill="#9ca3af", font=small)
    d.text((24, 72), f"Tendencia visual: {trend} | MACD/RSI anotados", fill="#d1d5db", font=small)

    if trend == "up":
        pts = [(50 + i * 40, 320 - i * 12 - (i % 2) * 6) for i in range(16)]
        color = "#22c55e"
    elif trend == "down":
        pts = [(50 + i * 40, 140 + i * 11 + (i % 2) * 5) for i in range(16)]
        color = "#ef4444"
    else:
        pts = [(50 + i * 40, 230 + ((-1) ** i) * 15) for i in range(16)]
        color = "#eab308"

    _draw_line_chart(d, pts, color=color)
    d.text((500, 100), "RSI~58", fill="#a5b4fc", font=small)
    d.text((500, 125), "MACD hist +", fill="#a5b4fc", font=small)

    if show_stop_zone:
        # Zona de stop visible (nivel explícito en la imagen para que el técnico lo lea)
        y_stop = 300
        d.line([(40, y_stop), (680, y_stop)], fill="#f97316", width=2)
        d.text((40, y_stop + 8), "STOP visible @ 6200 ARS", fill="#fdba74", font=small)
    else:
        d.text(
            (24, 360),
            "SIN nivel de stop ampliado — el Planificador debe pedir gap (no inventar)",
            fill="#fca5a5",
            font=small,
        )

    d.text((24, 390), "FIXTURE SINTÉTICA — dominio público / inventada", fill="#6b7280", font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> int:
    build_fci_panel(OUT / "fci-panel.png")
    build_trading_chart(
        OUT / "chart-ggal-no-stop.png",
        ticker="GGAL",
        title_extra="screening_poseido / falta gráfico ampliado para stop",
        trend="up",
        show_stop_zone=False,
    )
    build_trading_chart(
        OUT / "chart-ggal-with-stop.png",
        ticker="GGAL",
        title_extra="gráfico ampliado con zona de stop (resume HITL)",
        trend="up",
        show_stop_zone=True,
    )
    build_trading_chart(
        OUT / "chart-aapl-screening.png",
        ticker="AAPL",
        title_extra="screening_no_poseido (propósito del usuario)",
        trend="sideways",
        show_stop_zone=False,
    )
    print(f"Images written under {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
