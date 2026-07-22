"""Persistencia local del informe final como Markdown (salida de usuario)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("output/reports")


def _safe_id(raw: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", raw.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("-._")
    return cleaned or "sin-id"


def save_report_markdown(
    content: str,
    *,
    output_dir: Path | str,
    run_id: str | None = None,
    thread_id: str | None = None,
) -> Path:
    """Escribe el informe en UTF-8 y retorna el path absoluto.

    Nombre: ``informe-{run_id}.md``. Si no hay run_id usable, usa
    ``thread_id`` + timestamp UTC.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if run_id and run_id.strip():
        stem = _safe_id(run_id)
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = _safe_id(thread_id or "run")
        stem = f"{base}-{stamp}"

    path = (out / f"informe-{stem}.md").resolve()
    path.write_text(content, encoding="utf-8")
    return path
