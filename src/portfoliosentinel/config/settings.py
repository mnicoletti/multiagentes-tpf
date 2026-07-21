"""Settings de runtime (paths, flags). Sin hardcode de modelos — ver models.yaml."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
CONFIG_DIR = Path(__file__).resolve().parent
MODELS_YAML = Path(os.environ.get("PORTFOLIOSENTINEL_MODELS_YAML", CONFIG_DIR / "models.yaml"))
GUARDRAILS_YAML = Path(
    os.environ.get("PORTFOLIOSENTINEL_GUARDRAILS_YAML", CONFIG_DIR / "guardrails.yaml")
)
DEFAULT_FIXTURE_XLSX = REPO_ROOT / "fixtures" / "estadocuenta-sintetico.xlsx"
DEFAULT_IMAGES_DIR = REPO_ROOT / "fixtures" / "images"
ML_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "ml" / "trend"
# Checkpointer (ejecución) ≠ store de dominio (ADR-0003): dos SQLite distintas.
DEFAULT_CHECKPOINT_DB = REPO_ROOT / "data" / "checkpoints.sqlite"
DEFAULT_DOMAIN_DB = Path(
    os.environ.get(
        "PORTFOLIOSENTINEL_DOMAIN_DB",
        REPO_ROOT / "data" / "portfolio_store.sqlite",
    )
)

INVESTOR_ALIAS = "INV-001"

# F4 — market-data + RAG
DEFAULT_CHROMA_DIR = Path(
    os.environ.get("PORTFOLIOSENTINEL_CHROMA_DIR", REPO_ROOT / "data" / "chroma")
)
KNOWLEDGE_DIR = Path(os.environ.get("PORTFOLIOSENTINEL_KNOWLEDGE_DIR", REPO_ROOT / "knowledge"))
MARKET_FIXTURE_DIR = Path(os.environ.get("MARKET_FIXTURE_DIR", REPO_ROOT / "fixtures" / "market"))
WEB_FIXTURE_PATH = Path(
    os.environ.get(
        "PORTFOLIOSENTINEL_WEB_FIXTURE",
        REPO_ROOT / "fixtures" / "web" / "search_default.json",
    )
)
# Divergencia relativa MEP implícito vs API/fixture (porcentaje). Configurable.
MEP_DIVERGENCE_THRESHOLD_PCT = float(os.environ.get("MEP_DIVERGENCE_THRESHOLD_PCT", "2.0"))


def market_fixture_enabled() -> bool:
    return os.environ.get("MARKET_FIXTURE", "0").lower() in {"1", "true", "yes"}
