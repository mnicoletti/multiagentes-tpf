"""Salida estructurada del Planificador de Rebalanceo."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from portfoliosentinel.graph.state import ActionKind


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class PlannerActionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: ActionKind
    quantity: Decimal | None = None
    pct_of_position: Decimal | None = None
    rationale: str = ""
    stop_level: Decimal | None = None
    ml_signal_cited: bool = False
    risk_notes: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)

    @field_validator("quantity", "pct_of_position", "stop_level", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal | None:
        if v is None or v == "":
            return None
        return _as_decimal(v)  # type: ignore[arg-type]


class PlannerGapOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["missing_stop_chart"] = "missing_stop_chart"
    ticker: str
    detail: str


class PlannerLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[PlannerActionOut] = Field(min_length=1)
    capital_allocation: list[dict] = Field(default_factory=list)
    info_gaps: list[PlannerGapOut] = Field(default_factory=list)
    reasoning: str = Field(
        min_length=20,
        description=(
            "Debe citar predict_trend como insumo cuando se usó, nunca como conclusión sola"
        ),
    )
    notes: str = ""
