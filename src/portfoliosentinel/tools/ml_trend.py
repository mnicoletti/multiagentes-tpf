"""Tool ML predict_trend — LogReg versionada; insumo del Planificador, nunca decisión."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import joblib
from pydantic import BaseModel, ConfigDict, Field, field_validator

from portfoliosentinel.config.settings import REPO_ROOT

FEATURE_NAMES = (
    "rsi_14",
    "macd_hist",
    "sma_slope",
    "return_5d",
    "volume_z",
)

DEFAULT_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "ml" / "trend"
DEFAULT_MODEL_PATH = DEFAULT_ARTIFACT_DIR / "logreg_trend.joblib"
DEFAULT_META_PATH = DEFAULT_ARTIFACT_DIR / "meta.json"

TrendLabel = Literal["up", "down", "sideways"]


class TrendFeatures(BaseModel):
    """Features tipadas para predict_trend (mismos nombres que el entrenamiento)."""

    model_config = ConfigDict(extra="forbid")

    rsi_14: float = Field(ge=0, le=100)
    macd_hist: float
    sma_slope: float
    return_5d: float
    volume_z: float

    def as_vector(self) -> list[float]:
        return [float(getattr(self, name)) for name in FEATURE_NAMES]


class TrendPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: TrendLabel
    proba: float = Field(ge=0, le=1)
    proba_by_label: dict[str, float] = Field(default_factory=dict)
    model_version: str = ""
    features_used: list[str] = Field(default_factory=lambda: list(FEATURE_NAMES))

    @field_validator("proba", mode="before")
    @classmethod
    def _coerce_proba(cls, v: object) -> float:
        return float(v)  # type: ignore[arg-type]


class TrendModelError(RuntimeError):
    """Artefacto ML ausente o incompatible."""


@lru_cache(maxsize=1)
def _load_bundle(model_path: str) -> dict[str, Any]:
    path = Path(model_path)
    if not path.is_file():
        raise TrendModelError(
            f"Artefacto ML no encontrado: {path}. Corré: python scripts/train_trend_model.py"
        )
    bundle = joblib.load(path)
    if not isinstance(bundle, dict) or "model" not in bundle or "labels" not in bundle:
        raise TrendModelError(f"Artefacto inválido en {path}")
    return bundle


def predict_trend(
    features: TrendFeatures | dict[str, float] | list[float],
    *,
    model_path: str | Path | None = None,
) -> TrendPrediction:
    """Clasifica tendencia: {label, proba}. Un insumo más — no decisión autónoma."""
    path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
    bundle = _load_bundle(str(path.resolve()))
    model = bundle["model"]
    labels: list[str] = list(bundle["labels"])
    version = str(bundle.get("version", "unknown"))

    if isinstance(features, TrendFeatures):
        vec = features.as_vector()
    elif isinstance(features, dict):
        missing = [n for n in FEATURE_NAMES if n not in features]
        if missing:
            raise ValueError(f"Faltan features: {missing}")
        vec = [float(features[n]) for n in FEATURE_NAMES]
    else:
        if len(features) != len(FEATURE_NAMES):
            raise ValueError(
                f"Se esperaban {len(FEATURE_NAMES)} features, llegaron {len(features)}"
            )
        vec = [float(x) for x in features]

    proba_arr = model.predict_proba([vec])[0]
    idx = int(proba_arr.argmax())
    label = labels[idx]
    if label not in ("up", "down", "sideways"):
        raise TrendModelError(f"Label inesperado del modelo: {label}")
    proba_by = {labels[i]: float(proba_arr[i]) for i in range(len(labels))}
    return TrendPrediction(
        label=label,  # type: ignore[arg-type]
        proba=float(proba_arr[idx]),
        proba_by_label=proba_by,
        model_version=version,
        features_used=list(FEATURE_NAMES),
    )


def clear_model_cache() -> None:
    _load_bundle.cache_clear()
