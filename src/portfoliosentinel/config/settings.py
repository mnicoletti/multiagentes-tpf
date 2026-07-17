"""Settings de runtime (paths, flags). Sin hardcode de modelos — ver models.yaml."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
CONFIG_DIR = Path(__file__).resolve().parent
MODELS_YAML = CONFIG_DIR / "models.yaml"
DEFAULT_FIXTURE_XLSX = REPO_ROOT / "fixtures" / "estadocuenta-sintetico.xlsx"

INVESTOR_ALIAS = "INV-001"
