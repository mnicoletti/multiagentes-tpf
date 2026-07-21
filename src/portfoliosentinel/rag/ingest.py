"""Pipeline de ingesta: corpus knowledge/ + informes persistidos."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from portfoliosentinel.config.settings import DEFAULT_CHROMA_DIR, KNOWLEDGE_DIR
from portfoliosentinel.rag.store import (
    COLLECTION_KNOWLEDGE,
    COLLECTION_REPORTS,
    get_chroma_client,
    get_collection,
    upsert_documents,
)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_markdown_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parsea frontmatter YAML mínimo (key: value por línea)."""
    m = _FRONTMATTER_RE.match(text.strip() + ("\n" if not text.endswith("\n") else ""))
    if not m:
        # Intento sin exigir newline final del body
        m = _FRONTMATTER_RE.match(text.strip())
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip("\"'")
    return meta, m.group(2).strip()


def ingest_knowledge(
    knowledge_dir: str | Path | None = None,
    *,
    persist_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Indexa todos los .md de knowledge/ en la colección knowledge."""
    root = Path(knowledge_dir or KNOWLEDGE_DIR)
    client = get_chroma_client(persist_dir or DEFAULT_CHROMA_DIR)
    coll = get_collection(COLLECTION_KNOWLEDGE, client=client)

    ids: list[str] = []
    docs: list[str] = []
    metas: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_markdown_frontmatter(raw)
        doc_id = meta.get("id") or path.stem
        title = meta.get("title") or path.stem
        status = meta.get("status") or "draft"
        # Documento indexable: título + cuerpo (el frontmatter status queda en metadata).
        text = f"{title}\n\n{body}"
        ids.append(doc_id)
        docs.append(text)
        metas.append(
            {
                "source": str(path.name),
                "title": title,
                "status": status,
                "kind": "knowledge",
            }
        )

    upsert_documents(coll, ids=ids, documents=docs, metadatas=metas)
    return {"collection": COLLECTION_KNOWLEDGE, "count": len(ids), "ids": ids}


def ingest_report(
    *,
    report_id: str,
    run_id: str,
    content_md: str,
    persist_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Indexa un informe persistido (F3 write_report → Chroma)."""
    client = get_chroma_client(persist_dir or DEFAULT_CHROMA_DIR)
    coll = get_collection(COLLECTION_REPORTS, client=client)
    upsert_documents(
        coll,
        ids=[report_id],
        documents=[content_md],
        metadatas=[
            {
                "source": "report",
                "report_id": report_id,
                "run_id": run_id,
                "kind": "report",
            }
        ],
    )
    return {"collection": COLLECTION_REPORTS, "id": report_id, "run_id": run_id}


def ensure_knowledge_ingested(
    *,
    persist_dir: str | Path | None = None,
    knowledge_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Idempotente: (re)ingesta el corpus estático (bajo lock de Chroma)."""
    from portfoliosentinel.rag.store import CHROMA_IO_LOCK

    with CHROMA_IO_LOCK:
        return ingest_knowledge(knowledge_dir, persist_dir=persist_dir)
