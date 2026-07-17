"""Carga de modelos por rol vía init_chat_model (ADR-0009)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from portfoliosentinel.config.settings import MODELS_YAML

REQUIRED_ROLES = (
    "orquestador",
    "cartera",
    "mercado",
    "tecnico",
    "planificador",
    "redactor",
    "judge",
    "a2a",
)


class ModelsConfigError(ValueError):
    """models.yaml inválido o rol desconocido."""


@lru_cache(maxsize=1)
def load_models_config(path: str | None = None) -> dict[str, Any]:
    """Lee y valida `models.yaml`. No instancia LLMs."""
    yaml_path = Path(path) if path else MODELS_YAML
    if not yaml_path.is_file():
        raise ModelsConfigError(f"No se encontró models.yaml en {yaml_path}")

    with yaml_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "roles" not in raw:
        raise ModelsConfigError("models.yaml debe tener la clave top-level 'roles'")

    roles = raw["roles"]
    if not isinstance(roles, dict):
        raise ModelsConfigError("'roles' debe ser un mapping")

    missing = [r for r in REQUIRED_ROLES if r not in roles]
    if missing:
        raise ModelsConfigError(f"Faltan roles en models.yaml: {missing}")

    for role, cfg in roles.items():
        if not isinstance(cfg, dict):
            raise ModelsConfigError(f"Rol '{role}' debe ser un mapping")
        for key in ("provider", "model"):
            if key not in cfg or not cfg[key]:
                raise ModelsConfigError(f"Rol '{role}' requiere '{key}'")
        params = cfg.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ModelsConfigError(f"Rol '{role}': 'params' debe ser un mapping")
        cfg["params"] = params

    return raw


def get_chat_model(role: str, *, config_path: str | None = None) -> BaseChatModel:
    """Instancia el chat model del rol usando solo YAML + init_chat_model."""
    config = load_models_config(config_path)
    roles = config["roles"]
    if role not in roles:
        known = ", ".join(sorted(roles))
        raise ModelsConfigError(f"Rol desconocido '{role}'. Conocidos: {known}")

    cfg = roles[role]
    # provider:model es el formato canónico de init_chat_model (LangChain).
    model_id = f"{cfg['provider']}:{cfg['model']}"
    return init_chat_model(model_id, **cfg["params"])
