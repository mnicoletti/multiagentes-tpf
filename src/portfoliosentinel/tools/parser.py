"""Parser determinista de estado de cuenta .xlsx (ADR-0002 / ADR-0006).

Fuente de verdad numérica: openpyxl + Pydantic. Ningún LLM toca estos números.
Scrubbing de PII (titular/comitente → INV-001) ocurre antes de devolver el snapshot.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from portfoliosentinel.config.settings import INVESTOR_ALIAS
from portfoliosentinel.tools.exceptions import (
    MalformedStatementError,
    RowValidationError,
    TotalsMismatchError,
)
from portfoliosentinel.tools.schemas import (
    AccountSnapshot,
    AssetClass,
    CashBalance,
    CurrencyCode,
    Position,
)

logger = logging.getLogger(__name__)

SECTION_MONEDAS = "MONEDAS"
SECTION_ACCIONES = "ACCIONES"
SECTION_BONOS = "BONOS"
SECTION_CEDEARS = "CEDEARS"
SECTION_TOTALES = "TOTALES"
ASSET_SECTIONS: tuple[AssetClass, ...] = ("ACCIONES", "BONOS", "CEDEARS")
ALL_SECTIONS = {SECTION_MONEDAS, *ASSET_SECTIONS, SECTION_TOTALES}


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_decimal(value: Any, *, context: str) -> Decimal:
    if value is None or _cell_str(value) == "":
        raise MalformedStatementError(f"Valor numérico vacío en {context}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Evitar binario flotante: pasar por str del repr exacto de openpyxl cuando sea Decimal.
        # openpyxl suele entregar float; usamos format que preserve centavos comunes.
        return Decimal(str(value))
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise MalformedStatementError(
            f"No se pudo interpretar número en {context}: {value!r}"
        ) from exc


def _parse_as_of(value: Any) -> date | None:
    if value is None or _cell_str(value) == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell_str(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise MalformedStatementError(f"Fecha de estado no reconocida: {value!r}")


def _quantize_cent(value: Decimal) -> Decimal:
    """Normaliza a centavos sin redondear montos intermedios: exige ya 2 decimales exactos."""
    normalized = value.quantize(Decimal("0.01"))
    if normalized != value:
        # Si trae más de 2 decimales no nulos, es malformado (prohibido redondear).
        raise RowValidationError(f"Monto con más de 2 decimales (prohibido redondear): {value}")
    return normalized


def _read_sheet_rows(path: Path) -> list[tuple[Any, ...]]:
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001 — tipamos como malformado
        raise MalformedStatementError(f"No se pudo abrir el .xlsx '{path}': {exc}") from exc

    try:
        if not wb.sheetnames:
            raise MalformedStatementError("El .xlsx no tiene hojas")
        ws = wb[wb.sheetnames[0]]
        rows: list[tuple[Any, ...]] = []
        for row in ws.iter_rows(values_only=True):
            rows.append(tuple(row))
        return rows
    finally:
        wb.close()


def _find_header_fields(rows: list[tuple[Any, ...]]) -> tuple[date | None, str | None, str | None]:
    """Extrae fecha / titular / comitente crudos (PII) del encabezado."""
    as_of: date | None = None
    titular: str | None = None
    comitente: str | None = None

    for row in rows:
        if not row:
            continue
        key = _cell_str(row[0]).casefold()
        val = row[1] if len(row) > 1 else None
        if key in {"fecha", "fecha de liquidación", "fecha liquidacion"}:
            as_of = _parse_as_of(val)
        elif key in {"titular", "cliente", "nombre"}:
            titular = _cell_str(val) or None
        elif key in {"comitente", "nro comitente", "número de comitente", "numero de comitente"}:
            comitente = _cell_str(val) or None
    return as_of, titular, comitente


def _iter_sections(
    rows: list[tuple[Any, ...]],
) -> dict[str, list[tuple[Any, ...]]]:
    """Parte la hoja en bloques por marcador de sección en columna A."""
    sections: dict[str, list[tuple[Any, ...]]] = {}
    current: str | None = None

    for row in rows:
        label = _cell_str(row[0]).upper() if row else ""
        if label in ALL_SECTIONS:
            current = label
            sections.setdefault(current, [])
            continue
        if current is not None:
            # Saltar filas de encabezado de columnas dentro de la sección
            headerish = label.casefold() in {
                "moneda",
                "ticker",
                "especie",
                "instrumento",
                "concepto",
            }
            if headerish:
                continue
            if all(_cell_str(c) == "" for c in row):
                continue
            sections[current].append(row)

    return sections


def _parse_cash(rows: list[tuple[Any, ...]]) -> list[CashBalance]:
    cash: list[CashBalance] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=1):
        currency_raw = _cell_str(row[0]).upper()
        if currency_raw not in {"ARS", "USD"}:
            raise MalformedStatementError(
                f"MONEDAS fila {idx}: moneda desconocida '{currency_raw}' (esperado ARS|USD)"
            )
        currency: CurrencyCode = currency_raw  # type: ignore[assignment]
        if currency in seen:
            raise MalformedStatementError(f"MONEDAS: moneda duplicada '{currency}'")
        seen.add(currency)
        raw_amount = row[1] if len(row) > 1 else None
        amount = _quantize_cent(_to_decimal(raw_amount, context=f"MONEDAS/{currency}"))
        cash.append(CashBalance(currency=currency, amount=amount))
    if "ARS" not in seen or "USD" not in seen:
        raise MalformedStatementError("MONEDAS debe incluir saldos ARS y USD")
    return cash


def _parse_positions(rows: list[tuple[Any, ...]], asset_class: AssetClass) -> list[Position]:
    positions: list[Position] = []
    for idx, row in enumerate(rows, start=1):
        if len(row) < 4:
            raise MalformedStatementError(
                f"{asset_class} fila {idx}: se esperaban Ticker|Cantidad|Precio|Total"
            )
        ticker = _cell_str(row[0]).upper()
        if not ticker:
            raise MalformedStatementError(f"{asset_class} fila {idx}: ticker vacío")
        quantity = _to_decimal(row[1], context=f"{asset_class}/{ticker}/cantidad")
        price = _quantize_cent(_to_decimal(row[2], context=f"{asset_class}/{ticker}/precio"))
        total = _quantize_cent(_to_decimal(row[3], context=f"{asset_class}/{ticker}/total"))
        expected = quantity * price
        expected_cents = expected.quantize(Decimal("0.01"))
        # Exactitud al centavo: el total declarado debe coincidir con qty*price
        # sin redondear el producto hacia el total.
        if expected != total and expected_cents != total:
            raise RowValidationError(
                f"{asset_class} {ticker}: cantidad×precio={expected} ≠ total={total}"
            )
        if expected != total:
            # producto con más de 2 decimales que no cierra exacto contra total
            raise RowValidationError(
                f"{asset_class} {ticker}: cantidad×precio={expected} ≠ total={total} "
                "(prohibido redondear)"
            )
        positions.append(
            Position(
                ticker=ticker,
                quantity=quantity,
                price=price,
                total=total,
                asset_class=asset_class,
            )
        )
    return positions


def _parse_totals(rows: list[tuple[Any, ...]]) -> tuple[Decimal, Decimal]:
    total_ars: Decimal | None = None
    total_usd: Decimal | None = None
    for row in rows:
        key = _cell_str(row[0]).casefold()
        val = row[1] if len(row) > 1 else None
        if key in {"total ars", "total_ars", "ars"}:
            total_ars = _quantize_cent(_to_decimal(val, context="TOTALES/ARS"))
        elif key in {"total usd", "total_usd", "usd"}:
            total_usd = _quantize_cent(_to_decimal(val, context="TOTALES/USD"))
    if total_ars is None or total_usd is None:
        raise MalformedStatementError("TOTALES debe declarar 'Total ARS' y 'Total USD'")
    if total_usd == 0:
        raise MalformedStatementError("Total USD no puede ser cero (MEP indefinido)")
    return total_ars, total_usd


def _validate_portfolio_total_ars(
    cash: list[CashBalance],
    positions: list[Position],
    total_ars: Decimal,
) -> None:
    cash_ars = next(c.amount for c in cash if c.currency == "ARS")
    positions_sum = sum((p.total for p in positions), Decimal("0.00"))
    computed = cash_ars + positions_sum
    if computed != total_ars:
        raise TotalsMismatchError(
            f"Total ARS declarado={total_ars} ≠ cash_ARS+posiciones={computed}"
        )


def parse_account_statement(path: str | Path) -> AccountSnapshot:
    """Parsea un .xlsx de estado de cuenta → AccountSnapshot scrubbeado.

    - Valida totales fila-a-fila (cantidad × precio = total).
    - Valida Total ARS = cash ARS + suma de posiciones.
    - Deriva MEP implícito = total_ars / total_usd (sin redondeo).
    - Scrubbea titular/comitente → INV-001 antes de armar el snapshot.
    """
    xlsx_path = Path(path)
    if not xlsx_path.is_file():
        raise MalformedStatementError(f"Archivo inexistente: {xlsx_path}")

    rows = _read_sheet_rows(xlsx_path)
    if not rows:
        raise MalformedStatementError("El .xlsx está vacío")

    as_of, titular_raw, comitente_raw = _find_header_fields(rows)
    # Scrubbing ANTES de construir cualquier estructura que vea un LLM o se persista.
    if titular_raw or comitente_raw:
        logger.info(
            "pii_scrubbed",
            extra={
                "investor_alias": INVESTOR_ALIAS,
                "had_titular": bool(titular_raw),
                "had_comitente": bool(comitente_raw),
            },
        )

    sections = _iter_sections(rows)
    for required in (SECTION_MONEDAS, *ASSET_SECTIONS, SECTION_TOTALES):
        if required not in sections:
            raise MalformedStatementError(f"Falta la sección obligatoria '{required}'")

    cash = _parse_cash(sections[SECTION_MONEDAS])
    positions: list[Position] = []
    for asset_class in ASSET_SECTIONS:
        positions.extend(_parse_positions(sections[asset_class], asset_class))

    total_ars, total_usd = _parse_totals(sections[SECTION_TOTALES])
    _validate_portfolio_total_ars(cash, positions, total_ars)

    mep_implied = total_ars / total_usd  # Decimal exacto; sin round()

    snapshot = AccountSnapshot(
        investor_alias=INVESTOR_ALIAS,
        as_of=as_of,
        cash=cash,
        positions=positions,
        total_ars=total_ars,
        total_usd=total_usd,
        mep_implied=mep_implied,
    )

    logger.info(
        "statement_parsed",
        extra={
            "investor_alias": snapshot.investor_alias,
            "positions": len(snapshot.positions),
            "total_ars": str(snapshot.total_ars),
            "total_usd": str(snapshot.total_usd),
            "mep_implied": str(snapshot.mep_implied),
        },
    )
    return snapshot
