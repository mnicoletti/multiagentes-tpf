"""SQLite append-only del store de dominio (SPEC §5, ADR-0003).

Solo INSERT y SELECT. Prohibido UPDATE/DELETE sobre snapshots, constraints, reports.
Revocar una restricción = INSERT de un registro nuevo con status=revoked.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ConstraintStatus = Literal["active", "revoked"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    data_json TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS constraints (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked'))
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    content_md TEXT NOT NULL
);
"""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _constraint_key(rule_json: dict[str, Any]) -> tuple[str | None, str]:
    ticker = rule_json.get("ticker")
    rule = str(rule_json.get("rule", ""))
    return (ticker.upper() if isinstance(ticker, str) and ticker else None, rule)


class PortfolioStore:
    """Acceso append-only al SQLite de dominio (distinto del checkpointer)."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PortfolioStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- snapshots ---

    def write_snapshot(self, data: dict[str, Any], *, source: str) -> dict[str, Any]:
        """INSERT de un snapshot. Nunca update."""
        row_id = str(uuid.uuid4())
        ts = _utc_now_iso()
        self._conn.execute(
            "INSERT INTO snapshots (id, ts, data_json, source) VALUES (?, ?, ?, ?)",
            (row_id, ts, json.dumps(data, ensure_ascii=False, default=str), source),
        )
        self._conn.commit()
        return {"id": row_id, "ts": ts, "source": source}

    def read_last_snapshot(self) -> dict[str, Any] | None:
        """Último snapshot por ts (y id como desempate)."""
        cur = self._conn.execute(
            "SELECT id, ts, data_json, source FROM snapshots ORDER BY ts DESC, id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "ts": row["ts"],
            "source": row["source"],
            "data": json.loads(row["data_json"]),
        }

    def count_snapshots(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM snapshots")
        return int(cur.fetchone()["n"])

    # --- constraints ---

    def write_constraint(
        self,
        *,
        rule: str,
        ticker: str | None = None,
        status: ConstraintStatus = "active",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """INSERT de restricción (activa o revoked). Nunca update del registro viejo."""
        row_id = str(uuid.uuid4())
        ts = _utc_now_iso()
        rule_json: dict[str, Any] = {"rule": rule, "ticker": ticker}
        if extra:
            rule_json.update(extra)
        self._conn.execute(
            "INSERT INTO constraints (id, ts, rule_json, status) VALUES (?, ?, ?, ?)",
            (row_id, ts, json.dumps(rule_json, ensure_ascii=False), status),
        )
        self._conn.commit()
        return {
            "id": row_id,
            "ts": ts,
            "status": status,
            "rule": rule,
            "ticker": ticker,
            "rule_json": rule_json,
        }

    def revoke_constraint(self, *, rule: str, ticker: str | None = None) -> dict[str, Any]:
        """Revocación append-only: INSERT status=revoked; el activo previo queda intacto."""
        return self.write_constraint(rule=rule, ticker=ticker, status="revoked")

    def read_active_constraints(self) -> list[dict[str, Any]]:
        """Activas = último evento por (ticker, rule) con status=active."""
        cur = self._conn.execute(
            "SELECT id, ts, rule_json, status FROM constraints ORDER BY ts ASC, id ASC"
        )
        latest: dict[tuple[str | None, str], dict[str, Any]] = {}
        for row in cur.fetchall():
            rule_json = json.loads(row["rule_json"])
            key = _constraint_key(rule_json)
            latest[key] = {
                "id": row["id"],
                "ts": row["ts"],
                "status": row["status"],
                "rule": rule_json.get("rule", ""),
                "ticker": rule_json.get("ticker"),
                "rule_json": rule_json,
            }
        return [c for c in latest.values() if c["status"] == "active"]

    def list_constraint_rows(self) -> list[dict[str, Any]]:
        """Todos los registros (auditoría). Solo SELECT."""
        cur = self._conn.execute(
            "SELECT id, ts, rule_json, status FROM constraints ORDER BY ts ASC, id ASC"
        )
        out: list[dict[str, Any]] = []
        for row in cur.fetchall():
            rule_json = json.loads(row["rule_json"])
            out.append(
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "status": row["status"],
                    "rule_json": rule_json,
                }
            )
        return out

    # --- reports ---

    def write_report(self, *, run_id: str, content_md: str) -> dict[str, Any]:
        """INSERT de informe. Nunca update."""
        row_id = str(uuid.uuid4())
        ts = _utc_now_iso()
        self._conn.execute(
            "INSERT INTO reports (id, run_id, ts, content_md) VALUES (?, ?, ?, ?)",
            (row_id, run_id, ts, content_md),
        )
        self._conn.commit()
        return {"id": row_id, "run_id": run_id, "ts": ts}

    def list_reports(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT id, run_id, ts, content_md FROM reports ORDER BY ts ASC, id ASC"
        )
        return [
            {
                "id": row["id"],
                "run_id": row["run_id"],
                "ts": row["ts"],
                "content_md": row["content_md"],
            }
            for row in cur.fetchall()
        ]

    def count_reports(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM reports")
        return int(cur.fetchone()["n"])

    def schema_sql(self) -> str:
        """DDL visible para DoD / inspección."""
        cur = self._conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name IN ('snapshots', 'constraints', 'reports') ORDER BY name"
        )
        return "\n\n".join(f"{row['sql']};" for row in cur.fetchall())
