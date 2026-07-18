"""Salida estructurada del Analista de Cartera (solo juicio semántico; sin números inventados)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClusterAssignment(BaseModel):
    """Asignación semántica: el LLM elige name/driver/tickers; los pesos se calculan afuera."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Nombre corto del cluster por driver (ej. 'energía argentina'), "
            "nunca por sección contable"
        )
    )
    driver: str = Field(description="Driver de riesgo en una línea")
    tickers: list[str] = Field(
        min_length=1,
        description="Al menos un ticker del snapshot; sin listas vacías",
    )


class CarteraLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clusters: list[ClusterAssignment] = Field(
        min_length=1,
        description="Partición completa del snapshot: cada ticker en exactamente un cluster",
    )
    concentrations: list[str] = Field(
        description="Notas de concentración por posición y por cluster",
        min_length=1,
    )
    structural_diagnosis: str = Field(
        description="Exactamente una frase de diagnóstico estructural",
        min_length=10,
    )

    @field_validator("structural_diagnosis")
    @classmethod
    def _one_sentence(cls, v: str) -> str:
        text = " ".join(v.strip().split())
        if not text:
            raise ValueError("diagnóstico vacío")
        return text
