"""Validator de hard constraints + linter de informe (SPEC §8.3, ADR-0006).

Código puro + YAML — NUNCA un prompt.
- Plan rechazado → feedback al Planificador.
- Informe rechazado → feedback al Redactor; el informe NO sale.
"""

from __future__ import annotations

import re
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
    ReportLintResult,
    Snapshot,
    ValidationResult,
    ValidationViolation,
)

DEFAULT_GUARDRAILS_YAML = CONFIG_DIR / "guardrails.yaml"

SELL_LIKE = frozenset({"salir", "tomar_ganancia_parcial", "reducir"})

# Líneas machine-checkables del Redactor (sección 7).
_ACTION_LINE_RE = re.compile(
    r"^\s*-\s*ticker=(?P<ticker>[A-Za-z0-9.]+)\s*;\s*"
    r"action=(?P<action>[a-z_]+)\s*;\s*"
    r"qty=(?P<qty>[0-9]+(?:\.[0-9]+)?|null|none|-)\s*"
    r"(?:;\s*ref=(?P<ref>[^\n]+))?",
    re.IGNORECASE | re.MULTILINE,
)


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


def max_report_linter_retries(path: str | None = None) -> int:
    cfg = load_guardrails(path)
    return int(cfg.get("report_linter", {}).get("max_retries", 2))


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


def parse_report_actions(report_md: str) -> list[dict[str, Any]]:
    """Extrae acciones machine-checkables del bloque Acciones_verificables."""
    actions: list[dict[str, Any]] = []
    for m in _ACTION_LINE_RE.finditer(report_md or ""):
        qty_raw = m.group("qty").strip().lower()
        qty: Decimal | None
        if qty_raw in {"null", "none", "-"}:
            qty = None
        else:
            qty = Decimal(qty_raw)
        actions.append(
            {
                "ticker": m.group("ticker").upper(),
                "action": m.group("action").lower(),
                "quantity": qty,
                "ref": (m.group("ref") or "").strip(),
            }
        )
    return actions


def lint_report(
    report_md: str,
    *,
    snapshot: Snapshot,
    constraints: list[Constraint],
    attempt: int,
    guardrails_path: str | None = None,
) -> ReportLintResult:
    """Audita el informe contra report_rules YAML. approved=False → el informe NO sale."""
    cfg = load_guardrails(guardrails_path)
    rules = cfg.get("report_rules") or []
    violations: list[ValidationViolation] = []
    holdings = _holding_qty(snapshot)
    restricted = _restricted_tickers(constraints)
    text = report_md or ""
    text_lower = text.lower()
    parsed_actions = parse_report_actions(text)

    for rule in rules:
        if rule.get("type") != "report_linter":
            continue
        rule_id = str(rule.get("id", ""))
        params = rule.get("params") or {}

        if rule_id == "disclaimer-present":
            required = list(params.get("required_substrings") or [])
            for needle in required:
                if needle.lower() not in text_lower:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            message=(
                                f"Violación {rule_id}: falta substring requerido "
                                f"'{needle}' en el descargo."
                            ),
                        )
                    )

        elif rule_id == "no-execution-language":
            for pat in params.get("forbidden_patterns") or []:
                if str(pat).lower() in text_lower:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            message=(
                                f"Violación {rule_id}: lenguaje de ejecución prohibido ('{pat}')."
                            ),
                        )
                    )

        elif rule_id == "report-structure":
            headings = list(params.get("required_headings") or [])
            for heading in headings:
                if heading not in text:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            message=(f"Violación {rule_id}: falta sección marcada '{heading}'."),
                        )
                    )

        elif rule_id == "no-sell-restricted":
            blocked = set(params.get("blocked_actions") or list(SELL_LIKE))
            sell_verbs = [str(v).lower() for v in (params.get("sell_verbs") or ["vender"])]
            for action in parsed_actions:
                ticker = action["ticker"]
                if ticker in restricted and action["action"] in blocked:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: el informe recomienda "
                                f"'{action['action']}' sobre restringido {ticker}."
                            ),
                        )
                    )
            # Free-text: recomendación positiva de venta (ignorar negaciones cercanas:
            # "no vender", "no se pueda vender", "no poder vender", etc.).
            for ticker in restricted:
                for verb in sell_verbs:
                    pattern = re.compile(
                        rf"\b{re.escape(verb)}\s+{re.escape(ticker)}\b",
                        re.IGNORECASE,
                    )
                    for match in pattern.finditer(text):
                        prefix = text[max(0, match.start() - 28) : match.start()].lower()
                        if re.search(r"\bno\b", prefix):
                            continue
                        violations.append(
                            ValidationViolation(
                                rule_id=rule_id,
                                ticker=ticker,
                                message=(
                                    f"Violación {rule_id}: texto libre sugiere "
                                    f"'{verb} {ticker}' (restringido)."
                                ),
                            )
                        )

        elif rule_id == "qty-within-holdings":
            for action in parsed_actions:
                if action["action"] not in SELL_LIKE:
                    continue
                qty = action["quantity"]
                if qty is None:
                    continue
                ticker = action["ticker"]
                held = holdings.get(ticker)
                if held is None:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: {ticker} no está en el snapshot; "
                                "qty de venta inválida."
                            ),
                        )
                    )
                    continue
                if qty > held:
                    violations.append(
                        ValidationViolation(
                            rule_id=rule_id,
                            ticker=ticker,
                            message=(
                                f"Violación {rule_id}: qty {qty} > tenencia {held} "
                                f"de {ticker} en el informe."
                            ),
                        )
                    )

    # Deduplicar mensajes idénticos (p.ej. verbos repetidos).
    seen: set[str] = set()
    unique: list[ValidationViolation] = []
    for v in violations:
        key = f"{v.rule_id}|{v.ticker}|{v.message}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)

    feedback = [v.message for v in unique]
    return ReportLintResult(
        approved=len(unique) == 0,
        feedback=feedback,
        violations=unique,
        attempt=attempt,
    )


class ValidatorTrace(BaseModel):
    """Traza serializable para DoD / evidencias."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    approved: bool
    violations: list[ValidationViolation] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
