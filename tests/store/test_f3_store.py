"""Tests F3: store append-only, echo-back, modo degradado (sin LLM)."""

from __future__ import annotations

import re
import sqlite3
import subprocess
import uuid
from pathlib import Path

from mcp_servers.portfolio_store.db import PortfolioStore
from portfoliosentinel.config.settings import DEFAULT_FIXTURE_XLSX
from portfoliosentinel.graph.builder import build_graph
from portfoliosentinel.graph.checkpointer import get_checkpointer
from portfoliosentinel.graph.state import RunInputs

FIXTURE = DEFAULT_FIXTURE_XLSX
REPO_ROOT = Path(__file__).resolve().parents[2]

# Código de dominio que debe ser append-only (excluye checkpointer de LangGraph).
_APPEND_ONLY_GLOBS = [
    "mcp_servers/portfolio_store/**/*.py",
    "src/portfoliosentinel/tools/portfolio_store.py",
    "src/portfoliosentinel/graph/nodes.py",
]


def _initial_state(*, xlsx: str | None, run_id: str, **input_kw) -> dict:
    return {
        "run_id": run_id,
        "inputs": RunInputs(xlsx_path=xlsx, auto_confirm_constraints=True, **input_kw),
        "snapshot": None,
        "degraded_mode": False,
        "constraints": [],
        "prev_snapshot": None,
        "staleness": None,
        "diagnosis": None,
        "market_context": None,
        "technical_readings": [],
        "plan": None,
        "validation": None,
        "a2a_review": None,
        "info_gaps": [],
        "report": None,
    }


def test_schema_append_only_tables(tmp_path: Path):
    store = PortfolioStore(tmp_path / "domain.sqlite")
    try:
        ddl = store.schema_sql()
        assert "CREATE TABLE" in ddl
        assert "snapshots" in ddl
        assert "constraints" in ddl
        assert "reports" in ddl
        # Sin triggers de update/delete en el schema.
        assert "UPDATE" not in ddl.upper()
        assert "DELETE" not in ddl.upper()
    finally:
        store.close()


def test_grep_no_update_delete_in_domain_code():
    """DoD: cero UPDATE/DELETE SQL sobre snapshots/constraints/reports."""
    # Solo sentencias SQL (no dict.update / métodos Python).
    pattern = re.compile(
        r"""(?ix)
        (?:EXECUTE|EXECUTESCRIPT)\s*\([^)]*\b(UPDATE|DELETE)\b
        |
        [\"'].*\b(UPDATE|DELETE)\s+(?:FROM\s+)?(?:snapshots|constraints|reports)\b
        |
        \b(UPDATE|DELETE)\s+(?:FROM\s+)?(?:snapshots|constraints|reports)\b
        """
    )
    offenders: list[str] = []
    for glob in _APPEND_ONLY_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert offenders == [], "UPDATE/DELETE SQL encontrados:\n" + "\n".join(offenders)


def test_two_consecutive_runs_two_snapshots_two_reports(tmp_path: Path):
    """DoD: dos corridas consecutivas → 2 snapshots + 2 informes-stub."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    store = PortfolioStore(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        graph = build_graph(
            checkpointer=checkpointer,
            store=store,
            include_cartera=False,
        )
        for i in range(2):
            run_id = f"run-{i}-{uuid.uuid4().hex[:8]}"
            config = {"configurable": {"thread_id": run_id}}
            result = graph.invoke(
                _initial_state(xlsx=str(FIXTURE), run_id=run_id),
                config=config,
            )
            assert result["report"] is not None
            assert "Informe stub" in result["report"]
            assert result["degraded_mode"] is False

        assert store.count_snapshots() == 2
        assert store.count_reports() == 2
        reports = store.list_reports()
        assert len(reports) == 2
        assert all("Informe stub" in r["content_md"] for r in reports)

        # Inspección SQLite cruda: solo INSERTs vía conteo; filas intactas.
        raw = sqlite3.connect(domain)
        try:
            n_snap = raw.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            n_rep = raw.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
            assert n_snap == 2
            assert n_rep == 2
        finally:
            raw.close()
    finally:
        conn.close()
        store.close()


def test_revoke_constraint_inserts_new_row(tmp_path: Path):
    """DoD: revocar crea registro nuevo; el viejo queda intacto."""
    store = PortfolioStore(tmp_path / "domain.sqlite")
    try:
        active = store.write_constraint(rule="no vender YPFD", ticker="YPFD", status="active")
        old_id = active["id"]
        old_ts = active["ts"]

        revoked = store.revoke_constraint(rule="no vender YPFD", ticker="YPFD")
        assert revoked["id"] != old_id
        assert revoked["status"] == "revoked"

        rows = store.list_constraint_rows()
        assert len(rows) == 2
        by_id = {r["id"]: r for r in rows}
        assert by_id[old_id]["status"] == "active"
        assert by_id[old_id]["ts"] == old_ts
        assert by_id[revoked["id"]]["status"] == "revoked"

        # Ya no figura como activa.
        assert store.read_active_constraints() == []

        # Consulta SQL explícita (evidencia DoD).
        raw = sqlite3.connect(tmp_path / "domain.sqlite")
        try:
            cur = raw.execute("SELECT id, status FROM constraints ORDER BY ts ASC, id ASC")
            sql_rows = cur.fetchall()
            assert sql_rows == [(old_id, "active"), (revoked["id"], "revoked")]
        finally:
            raw.close()
    finally:
        store.close()


def test_degraded_mode_loads_previous_snapshot_with_staleness(tmp_path: Path):
    """DoD: sin .xlsx → degraded_mode=True, snapshot anterior, staleness visible."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    store = PortfolioStore(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        # Semilla: una corrida con .xlsx persiste snapshot.
        seed_id = f"seed-{uuid.uuid4().hex[:8]}"
        graph = build_graph(checkpointer=checkpointer, store=store, include_cartera=False)
        graph.invoke(
            _initial_state(xlsx=str(FIXTURE), run_id=seed_id),
            config={"configurable": {"thread_id": seed_id}},
        )
        assert store.count_snapshots() == 1
        last = store.read_last_snapshot()
        assert last is not None
        expected_positions = len(last["data"]["positions"])

        # Segunda corrida sin .xlsx.
        deg_id = f"deg-{uuid.uuid4().hex[:8]}"
        result = graph.invoke(
            _initial_state(xlsx=None, run_id=deg_id),
            config={"configurable": {"thread_id": deg_id}},
        )
        assert result["degraded_mode"] is True
        assert result["snapshot"] is not None
        assert len(result["snapshot"].positions) == expected_positions
        assert result["staleness"] is not None
        assert result["staleness"].block_fine_quantities is True
        assert "desactualizados" in result["staleness"].warning
        assert result["staleness"].snapshot_id == last["id"]
        # En degradado no se escribe snapshot nuevo; sí informe-stub.
        assert store.count_snapshots() == 1
        assert store.count_reports() == 2
        assert "Staleness" in (result["report"] or "")
    finally:
        conn.close()
        store.close()


def test_echo_back_persists_new_constraint_and_requires_confirmation(tmp_path: Path):
    """Restricción nueva se confirma en echo-back y queda activa en BD."""
    domain = tmp_path / "domain.sqlite"
    ck = tmp_path / "ck.sqlite"
    store = PortfolioStore(domain)
    checkpointer, conn = get_checkpointer(ck)
    try:
        run_id = f"c-{uuid.uuid4().hex[:8]}"
        graph = build_graph(checkpointer=checkpointer, store=store, include_cartera=False)
        result = graph.invoke(
            _initial_state(
                xlsx=str(FIXTURE),
                run_id=run_id,
                new_constraints_text="no vender YPFD",
            ),
            config={"configurable": {"thread_id": run_id}},
        )
        assert len(result["constraints"]) == 1
        assert result["constraints"][0].ticker == "YPFD"
        assert result["constraints"][0].confirmed is True
        assert result["constraints"][0].source == "echo"
        active = store.read_active_constraints()
        assert len(active) == 1
        assert active[0]["ticker"] == "YPFD"
    finally:
        conn.close()
        store.close()


def test_fastmcp_tools_registered():
    """Las 5 tools de SPEC §7.1 existen en el server FastMCP."""
    from mcp_servers.portfolio_store import server as srv

    # FastMCP guarda tools en mcp._tool_manager o list_tools async; inspeccionamos el decorador.
    names = set(srv.mcp._tool_manager._tools.keys())  # noqa: SLF001
    assert names == {
        "read_active_constraints",
        "read_last_snapshot",
        "write_snapshot",
        "write_report",
        "list_reports",
    }


def test_rg_update_delete_subprocess_evidence():
    """Evidencia DoD vía ripgrep (salida vacía de sentencias SQL mutables)."""
    result = subprocess.run(
        [
            "rg",
            "-n",
            r"\b(UPDATE|DELETE)\s+(snapshots|constraints|reports)\b",
            "mcp_servers/portfolio_store",
            "src/portfoliosentinel/tools/portfolio_store.py",
            "src/portfoliosentinel/graph/nodes.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # rg exit 1 = sin matches (lo que queremos).
    assert result.returncode in (0, 1)
    assert result.stdout.strip() == "", result.stdout
