"""Salida estructurada del Analista Técnico (visión multimodal)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class TecnicoImageReading(BaseModel):
    """Juicio semántico sobre UNA imagen. Números de stop solo si son visibles."""

    model_config = ConfigDict(extra="forbid")

    ticker: str | None = None
    summary: str = Field(min_length=5)
    trend: str | None = None
    indicators: dict[str, Any] = Field(default_factory=dict)
    verdict: str | None = None
    needs_stop_level: bool = False
    stop_level: Decimal | None = Field(
        default=None,
        description=(
            "Solo si el nivel es legible en la imagen o lo aportó el usuario; nunca inventado"
        ),
    )
    stop_visible_in_image: bool = False

    @field_validator("stop_level", mode="before")
    @classmethod
    def _coerce_stop(cls, v: object) -> Decimal | None:
        if v is None or v == "":
            return None
        return _as_decimal(v)  # type: ignore[arg-type]


class TecnicoLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: list[TecnicoImageReading] = Field(min_length=1)
