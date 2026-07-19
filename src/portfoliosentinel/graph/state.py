"""PortfolioState y sub-esquemas Pydantic (SPEC §4.2).

Todos los sub-esquemas son serializables para el checkpointer SQLite (ADR-0003).
Campos de fases posteriores viven acá aunque F2 no los pueble.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from portfoliosentinel.tools.schemas import AccountSnapshot

# Alias canónico del SPEC: Snapshot = salida tipada del parser.
Snapshot = AccountSnapshot


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class Constraint(BaseModel):
    """Restricción dura del usuario (persistida en F3+ vía MCP)."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    rule: str
    ticker: str | None = None
    status: Literal["active", "revoked", "pending_confirmation"] = "active"
    source: Literal["db", "run", "echo"] = "run"
    confirmed: bool = False


class StalenessInfo(BaseModel):
    """Marca de staleness en modo degradado (SPEC §6.1, ADR-0003)."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str | None = None
    snapshot_ts: str | None = None
    warning: str
    block_fine_quantities: bool = True


class RunInputs(BaseModel):
    """Inputs de una corrida on-demand."""

    model_config = ConfigDict(extra="forbid")

    xlsx_path: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    image_purposes: dict[str, str] = Field(
        default_factory=dict,
        description="path → propósito declarado por el usuario (no se infiere)",
    )
    capital_new_ars: Decimal | None = None
    new_constraints_text: str | None = None
    # Restricciones estructuradas declaradas en esta corrida (antes del echo-back).
    new_constraints: list[Constraint] = Field(default_factory=list)
    # Si True, el orquestador no pausa: confirma todas las restricciones del echo-back.
    auto_confirm_constraints: bool = False
    user_notes: str | None = None

    @field_validator("capital_new_ars", mode="before")
    @classmethod
    def _coerce_capital(cls, v: object) -> Decimal | None:
        if v is None or v == "":
            return None
        return _as_decimal(v)  # type: ignore[arg-type]


class ClassWeight(BaseModel):
    """Peso de una clase contable sobre total_ars (aritmética determinista)."""

    model_config = ConfigDict(extra="forbid")

    asset_class: str
    total_ars: Decimal
    weight: Decimal

    @field_validator("total_ars", "weight", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class PositionWeight(BaseModel):
    """Peso de una posición individual sobre total_ars."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    asset_class: str
    total_ars: Decimal
    weight: Decimal

    @field_validator("total_ars", "weight", mode="before")
    @classmethod
    def _coerce(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class RiskCluster(BaseModel):
    """Cluster semántico por driver de riesgo (tickers del LLM; pesos deterministas)."""

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


class Diagnosis(BaseModel):
    """Radiografía del Analista de Cartera."""

    model_config = ConfigDict(extra="forbid")

    class_weights: list[ClassWeight]
    position_weights: list[PositionWeight]
    mep_implied: Decimal
    clusters: list[RiskCluster]
    concentrations: list[str] = Field(default_factory=list)
    structural_diagnosis: str = Field(description="Diagnóstico estructural en una frase")

    @field_validator("mep_implied", mode="before")
    @classmethod
    def _coerce_mep(cls, v: object) -> Decimal:
        return _as_decimal(v)  # type: ignore[arg-type]


class MarketContext(BaseModel):
    """Stub F4 — contexto de mercado por instrumento/sector."""

    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    instruments: list[dict[str, Any]] = Field(default_factory=list)
    mep_warning: str | None = None


class TechnicalReading(BaseModel):
    """Stub F5 — lectura multimodal de una imagen."""

    model_config = ConfigDict(extra="forbid")

    image_path: str
    purpose: str
    summary: str = ""


class RebalancePlan(BaseModel):
    """Stub F5 — plan de rebalanceo del Planificador."""

    model_config = ConfigDict(extra="forbid")

    actions: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class ValidationResult(BaseModel):
    """Stub F5 — veredicto del validator de hard constraints."""

    model_config = ConfigDict(extra="forbid")

    approved: bool = False
    feedback: list[str] = Field(default_factory=list)
    attempt: int = 0


class ExternalReview(BaseModel):
    """Stub F8 — observaciones A2A (no bloquean)."""

    model_config = ConfigDict(extra="forbid")

    available: bool = False
    observations: list[str] = Field(default_factory=list)


class InfoGap(BaseModel):
    """Gap de información que dispara interrupt() (F5)."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    ticker: str | None = None
    detail: str


class PortfolioState(TypedDict, total=False):
    """Estado compartido del grafo LangGraph (SPEC §4.2)."""

    run_id: str
    inputs: RunInputs
    snapshot: Snapshot | None
    degraded_mode: bool
    constraints: list[Constraint]
    prev_snapshot: Snapshot | None
    staleness: StalenessInfo | None
    diagnosis: Diagnosis | None
    market_context: MarketContext | None
    technical_readings: list[TechnicalReading]
    plan: RebalancePlan | None
    validation: ValidationResult | None
    a2a_review: ExternalReview | None
    info_gaps: list[InfoGap]
    report: str | None
