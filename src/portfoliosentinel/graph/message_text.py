"""Helpers para normalizar respuestas de chat models (ADR-0009)."""

from __future__ import annotations

from typing import Any


def message_text(raw: Any) -> str:
    """Extrae texto de AIMessage / content blocks (str, dict, objetos con .text)."""
    content = getattr(raw, "content", raw)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
                continue
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(str(text))
                continue
            parts.append(str(block))
        return "".join(parts)
    return str(content)
