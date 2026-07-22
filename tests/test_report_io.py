"""Tests del guardado de informe Markdown."""

from __future__ import annotations

from pathlib import Path

from portfoliosentinel.tools.report_io import save_report_markdown


def test_save_report_markdown_writes_utf8_and_returns_absolute(tmp_path: Path):
    content = "# Informe\n\nDescargo de no-asesoramiento.\n"
    path = save_report_markdown(content, output_dir=tmp_path, run_id="e2e-demo-1")
    assert path.is_absolute()
    assert path.name == "informe-e2e-demo-1.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == content


def test_save_report_markdown_sanitizes_run_id(tmp_path: Path):
    path = save_report_markdown("x", output_dir=tmp_path / "nested", run_id="run/id:weird")
    assert path.parent == (tmp_path / "nested").resolve()
    assert path.name == "informe-run-id-weird.md"
    assert path.read_text(encoding="utf-8") == "x"


def test_save_report_markdown_fallback_thread_id(tmp_path: Path):
    path = save_report_markdown("y", output_dir=tmp_path, run_id=None, thread_id="thr-9")
    assert path.name.startswith("informe-thr-9-")
    assert path.name.endswith(".md")
    assert path.read_text(encoding="utf-8") == "y"
