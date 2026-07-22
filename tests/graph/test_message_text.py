"""Tests de extracción de texto de mensajes LLM."""

from __future__ import annotations

from types import SimpleNamespace

from portfoliosentinel.graph.message_text import message_text
from portfoliosentinel.graph.nodes_f6 import _looks_structured


def test_message_text_str():
    assert message_text(SimpleNamespace(content="hola")) == "hola"


def test_message_text_dict_blocks():
    raw = SimpleNamespace(content=[{"type": "text", "text": "A"}, {"type": "text", "text": "B"}])
    assert message_text(raw) == "AB"


def test_message_text_object_blocks():
    block = SimpleNamespace(text="bloque")
    raw = SimpleNamespace(content=[block])
    assert message_text(raw) == "bloque"


def test_looks_structured_requires_markers():
    bad = "informe corto sin secciones"
    assert not _looks_structured(bad)
    good = (
        "## 1. Encabezado\n"
        "Este sistema no constituye asesoramiento financiero y no ejecuta órdenes.\n"
        "## 7. Plan de acción consolidado\n"
    )
    assert _looks_structured(good)
