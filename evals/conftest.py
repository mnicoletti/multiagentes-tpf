"""Pytest fixtures compartidas del harness F7."""

from __future__ import annotations

import os

import pytest

from evals.harness import ensure_fixture_mode, reset_results, write_results_md


@pytest.fixture(scope="session", autouse=True)
def _fixture_mode_session():
    ensure_fixture_mode()
    reset_results()
    yield
    write_results_md()


@pytest.fixture(autouse=True)
def _fixture_mode_each():
    ensure_fixture_mode()
    # No filtrar red hacia Ollama local en tests del judge.
    os.environ.setdefault("MARKET_FIXTURE", "1")
