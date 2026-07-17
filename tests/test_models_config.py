"""Tests del loader de models.yaml (sin llamar a ningún LLM)."""

from __future__ import annotations

from portfoliosentinel.config.models import REQUIRED_ROLES, load_models_config


def test_models_yaml_has_all_roles():
    config = load_models_config()
    roles = config["roles"]
    for role in REQUIRED_ROLES:
        assert role in roles
        assert roles[role]["provider"]
        assert roles[role]["model"]
        assert isinstance(roles[role]["params"], dict)
