"""Chroma embebido persistido en disco (ADR-0004)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR
from portfoliosentinel.rag.embeddings import LocalHashEmbeddingFunction

COLLECTION_KNOWLEDGE = "knowledge"
COLLECTION_REPORTS = "reports"


def get_chroma_client(persist_dir: str | Path | None = None) -> chromadb.PersistentClient:
    path = Path(persist_dir or DEFAULT_CHROMA_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def get_collection(
    name: str,
    *,
    persist_dir: str | Path | None = None,
    client: chromadb.PersistentClient | None = None,
) -> Collection:
    cli = client or get_chroma_client(persist_dir)
    emb = LocalHashEmbeddingFunction()
    return cli.get_or_create_collection(
        name=name,
        embedding_function=emb,  # type: ignore[arg-type]
        metadata={"hnsw:space": "cosine"},
    )


def upsert_documents(
    collection: Collection,
    *,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]] | None = None,
) -> None:
    if not ids:
        return
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )
