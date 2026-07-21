"""RAG: ingesta + retrieval sobre Chroma embebido (ADR-0004)."""

from portfoliosentinel.rag.ingest import (
    ensure_knowledge_ingested,
    ingest_knowledge,
    ingest_report,
)
from portfoliosentinel.rag.retriever import format_hits_as_untrusted_context, retrieve

__all__ = [
    "ensure_knowledge_ingested",
    "ingest_knowledge",
    "ingest_report",
    "retrieve",
    "format_hits_as_untrusted_context",
]
