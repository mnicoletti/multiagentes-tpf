"""Chroma embebido persistido en disco (ADR-0004).

Cliente singleton por path + lock: chromadb no tolera PersistentClient
concurrentes sobre el mismo store (crash típico en fan-out mercado∥técnico).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection

from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR
from portfoliosentinel.rag.embeddings import LocalHashEmbeddingFunction

COLLECTION_KNOWLEDGE = "knowledge"
COLLECTION_REPORTS = "reports"

_CLIENTS: dict[str, chromadb.PersistentClient] = {}
_CLIENT_LOCK = threading.RLock()
# Serializa toda operación de lectura/escritura sobre Chroma (ingest + retrieve).
CHROMA_IO_LOCK = threading.RLock()


def get_chroma_client(persist_dir: str | Path | None = None) -> chromadb.PersistentClient:
    path = Path(persist_dir or DEFAULT_CHROMA_DIR).resolve()
    key = str(path)
    with _CLIENT_LOCK:
        existing = _CLIENTS.get(key)
        if existing is not None:
            return existing
        path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=key)
        _CLIENTS[key] = client
        return client


def get_collection(
    name: str,
    *,
    persist_dir: str | Path | None = None,
    client: chromadb.PersistentClient | None = None,
) -> Collection:
    with CHROMA_IO_LOCK:
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
    with CHROMA_IO_LOCK:
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )


def clear_chroma_client_cache() -> None:
    """Solo tests: libera referencias locales (no llama system.stop())."""
    with _CLIENT_LOCK:
        _CLIENTS.clear()
