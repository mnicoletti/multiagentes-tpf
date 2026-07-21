#!/usr/bin/env python3
"""Harness F7: un comando corre GC-1/GC-2 + E-1..E-4 y exige RESULTS.md."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evals" / "RESULTS.md"


def main() -> int:
    os.environ["MARKET_FIXTURE"] = "1"
    # Judge independiente (evals/judge/models.yaml). No compartir con agentes.
    os.environ.pop("PORTFOLIOSENTINEL_MODELS_YAML", None)

    print("[eval] MARKET_FIXTURE=1 — corriendo evals/ (GC-1, GC-2, E-1..E-4)", flush=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "evals", "-v", "--tb=short"],
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        return proc.returncode
    if not RESULTS.is_file():
        print("[eval] ERROR: no se generó evals/RESULTS.md", file=sys.stderr)
        return 1
    print(f"[eval] OK — resultados en {RESULTS}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
