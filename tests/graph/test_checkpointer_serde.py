"""Round-trip serde del checkpointer — tipos de dominio en allowlist msgpack."""

from __future__ import annotations

from portfoliosentinel.graph.checkpointer import _serde
from portfoliosentinel.graph.state import ReportLintResult


def test_report_lint_result_roundtrip():
    serde = _serde()
    original = ReportLintResult(
        approved=True,
        attempt=1,
        feedback=[],
        violations=[],
    )
    blob = serde.dumps_typed(original)
    restored = serde.loads_typed(blob)
    assert isinstance(restored, ReportLintResult)
    assert restored.approved is True
    assert restored.attempt == 1
