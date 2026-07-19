"""Settings de runtime (paths, flags). Sin hardcode de modelos — ver models.yaml."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
CONFIG_DIR = Path(__file__).resolve().parent
MODELS_YAML = Path(os.environ.get("PORTFOLIOSENTINEL_MODELS_YAML", CONFIG_DIR / "models.yaml"))
DEFAULT_FIXTURE_XLSX = REPO_ROOT / "fixtures" / "estadocuenta-sintetico.xlsx"
# Checkpointer (ejecución) ≠ store de dominio (ADR-0003): dos SQLite distintas.
DEFAULT_CHECKPOINT_DB = REPO_ROOT / "data" / "checkpoints.sqlite"
DEFAULT_DOMAIN_DB = Path(
    os.environ.get(
        "PORTFOLIOSENTINEL_DOMAIN_DB",
        REPO_ROOT / "data" / "portfolio_store.sqlite",
    )
)

INVESTOR_ALIAS = "INV-001"
