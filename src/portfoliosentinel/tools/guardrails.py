"""Validator determinista de hard constraints (SPEC §8.3, ADR-0006).

Código puro + YAML — NUNCA un prompt. Rechazo → feedback estructurado al Planificador.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from portfoliosentinel.config.settings import CONFIG_DIR
from portfoliosentinel.graph.state import (
    Constraint,
    PlanAction,
    RebalancePlan,
    Snapshot,
    ValidationResult,
    ValidationViolation,
)

DEFAULT_GUARDRAILS_YAML = CONFIG_DIR / "guardrails.yaml"

SELL_LIKE = frozenset({"salir", "tomar_ganancia_parcial", "reducir"})


class GuardrailsConfigError(ValueError):
    """guardrails.yaml inválido."""


@lru_cache(maxsize=1)
def load_guardrails(path: str | None = None) -> dict[str, Any]:
    yaml_path = Path(path) if path else DEFAULT_GUARDRAILS_YAML
    if not yaml_path.is_file():
        raise GuardrailsConfigError(f"No se encontró guardrails.yaml en {yaml_path}")
    with yaml_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or "rules" not in raw:
        raise GuardrailsConfigError("guardrails.yaml debe tener 'rules'")
    return raw


def max_validator_retries(path: str | None = None) -> int:
    cfg = load_guardrails(path)
    return int(cfg.get("validator", {}).get("max_retries", 2))


def _restricted_tickers(constraints: list[Constraint]) -> set[str]:
    out: set[str] = set()
    for c in constraints:
        if c.status != "active":
            continue
        if c.ticker:
            out.add(c.ticker.upper())
            continue
        # Fallback: parsear "no vender TICKER" del rule text.
        rule = (c.rule or "").lower()
        if "no vender" in rule:
            parts = rule.split()
            if parts:
                out.add(parts[-1].upper())
    return out


def _holding_qty(snapshot: Snapshot) -> dict[str, Decimal]:
    return {p.ticker.upper(): p.quantity for p in snapshot.positions}


def _as_actions(plan: RebalancePlan) -> list[PlanAction]:
    return list(plan.actions)


def validate_plan(
    plan: RebalancePlan,
    *,
    snapshot: Snapshot,
    constraints: list[Constraint],
    attempt: int,
    guardrails_path: str | None = None,
) -> ValidationResult:
    """Audita el plan contra hard constraints. approved=False → feedback para replan."""
    cfg = load_guardrails(guardrails_path)
    rules = cfg.get("rules") or []
    violations: list[ValidationViolation] = []
    holdings = _holding_qty(snapshot)
    restricted = _restricted_tickers(constraints)

    for rule in rules:
        if rule.get("type") != "hard_constraint":
            continue
        rule_id = str(rule.get("id", ""))
        params = rule.get("params") or {}

        if rule_id == "no-sell-restricted":
            blocked = set(params.get("blocked_actions") or list(SELL_LIKE))
            for action in _as_actions(plan):
                ticker = action.ticker.upper()
                if ticker in restricted and action.action in blocked:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: acción '{action.action}' "
                                f"sobre ticker restringido {ticker}. "
                                "No vender; señalar riesgo y proponer mitigación alternativa."
                            ),
                        )
                    )

        elif rule_id == "qty-within-holdings":
            for action in _as_actions(plan):
                if action.action not in SELL_LIKE:
                    continue
                if action.quantity is None:
                    continue
                ticker = action.ticker.upper()
                held = holdings.get(ticker)
                if held is None:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: {ticker} no está en el snapshot; "
                                "no se puede vender cantidad alguna."
                            ),
                        )
                    )
                    continue
                if action.quantity > held:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: qty {action.quantity} > "
                                f"tenencia {held} de {ticker}."
                            ),
                        )
                    )

    feedback = [v.message for v in violations]
    approved = len(violations) == 0
    return ValidationResult(
        approved=approved,
        feedback=feedback,
        violations=violations,
        attempt=attempt,
    )


class ValidatorTrace(BaseModel):
    """Traza serializable para DoD / evidencias."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    approved: bool
    violations: list[ValidationViolation] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
