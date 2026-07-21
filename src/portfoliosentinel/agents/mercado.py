"""Salida estructurada del Analista de Mercado (síntesis + citas; sin inventar FX/precios)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MercadoCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(description="id de doc RAG, URL web o 'market-data'")
    note: str = Field(description="Qué se usó de esa fuente")


class MercadoLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(
        min_length=20,
        description="Síntesis de contexto de mercado en rioplatense, con fecha",
    )
    instrument_notes: list[str] = Field(
        default_factory=list,
        description="Notas cortas por instrumento/sector (sin números inventados)",
    )
    citations: list[MercadoCitation] = Field(
        default_factory=list,
        description="Citas a RAG / web / market-data",
    )
    narrative_delta: str = Field(
        default="",
        description="Delta vs informes previos si hubo retrieval de reports; si no, vacío",
    )
