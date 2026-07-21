#!/usr/bin/env python3
"""Entrena LogReg de tendencia y versiona el artefacto en artifacts/ml/trend/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "artifacts" / "ml" / "trend"
VERSION = "1.0.0"

FEATURE_NAMES = ["rsi_14", "macd_hist", "sma_slope", "return_5d", "volume_z"]
LABELS = ["down", "sideways", "up"]


def _synthetic_dataset(n_per_class: int = 120, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Dataset sintético coherente con la semántica de indicadores."""
    rng = np.random.default_rng(seed)
    xs: list[np.ndarray] = []
    ys: list[int] = []

    # down: RSI bajo, MACD neg, slope neg, return neg
    for _ in range(n_per_class):
        xs.append(
            np.array(
                [
                    rng.uniform(15, 40),
                    rng.uniform(-2.0, -0.2),
                    rng.uniform(-0.05, -0.005),
                    rng.uniform(-0.08, -0.01),
                    rng.normal(0, 1),
                ]
            )
        )
        ys.append(0)

    # sideways: RSI medio, MACD ~0, slope ~0, return ~0
    for _ in range(n_per_class):
        xs.append(
            np.array(
                [
                    rng.uniform(40, 60),
                    rng.uniform(-0.3, 0.3),
                    rng.uniform(-0.008, 0.008),
                    rng.uniform(-0.015, 0.015),
                    rng.normal(0, 1),
                ]
            )
        )
        ys.append(1)

    # up: RSI alto, MACD pos, slope pos, return pos
    for _ in range(n_per_class):
        xs.append(
            np.array(
                [
                    rng.uniform(55, 85),
                    rng.uniform(0.2, 2.0),
                    rng.uniform(0.005, 0.05),
                    rng.uniform(0.01, 0.08),
                    rng.normal(0, 1),
                ]
            )
        )
        ys.append(2)

    return np.vstack(xs), np.array(ys)


def main() -> int:
    x, y = _synthetic_dataset()
    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=500,
                    random_state=42,
                ),
            ),
        ]
    )
    pipe.fit(x, y)
    acc = float(pipe.score(x, y))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = OUT_DIR / "logreg_trend.joblib"
    meta_path = OUT_DIR / "meta.json"

    bundle = {
        "model": pipe,
        "labels": LABELS,
        "feature_names": FEATURE_NAMES,
        "version": VERSION,
        "algorithm": "LogisticRegression (multinomial) + StandardScaler",
    }
    joblib.dump(bundle, model_path)

    meta = {
        "name": "predict_trend",
        "version": VERSION,
        "algorithm": bundle["algorithm"],
        "labels": LABELS,
        "feature_names": FEATURE_NAMES,
        "training_data": (
            "Dataset sintético (360 filas) con reglas de indicadores: "
            "RSI/MACD/sma_slope/return_5d/volume_z → up|down|sideways. "
            "No usa datos de mercado reales ni PII."
        ),
        "train_accuracy_in_sample": round(acc, 4),
        "intended_use": (
            "Insumo del Planificador de Rebalanceo. Nunca decisión autónoma "
            "ni sustituto de stops/restricciones."
        ),
        "artifact": str(model_path.relative_to(REPO_ROOT)),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {model_path} (in-sample acc={acc:.4f})")
    print(f"Wrote {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
