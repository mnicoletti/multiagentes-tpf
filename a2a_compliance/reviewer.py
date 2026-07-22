"""Revisor A2A: 1 LLM call + reglas deterministas (deliberadamente simple)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from a2a_compliance.rules import apply_compliance_rules

REVIEWER_SYSTEM = """Sos un agente de compliance de un bróker externo (simulado).
Revisás un plan de rebalanceo de forma CONSULTIVA: no bloqueás ni ejecutás.
Respondé SOLO JSON válido con esta forma:
{"approved": true|false, "observations": ["..."]}
Si no hay hallazgos semánticos, approved=true y observations=[].
Máximo 3 observaciones, una frase cada una, en español rioplatense.
No inventes números; no digas que el plan está "aprobado para ejecución".
"""


def _parse_llm_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"approved": True, "observations": []}


def _invoke_llm(plan_payload: dict[str, Any]) -> list[str]:
    """Un solo call al rol `a2a` vía init_chat_model. Si falla → sin obs LLM."""
    if os.environ.get("A2A_SKIP_LLM", "").lower() in {"1", "true", "yes"}:
        return []
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from portfoliosentinel.config.models import get_chat_model
        from portfoliosentinel.graph.message_text import message_text
    except Exception:  # noqa: BLE001
        return []

    try:
        model = get_chat_model("a2a")
        user = (
            "Plan a revisar (JSON):\n"
            + json.dumps(plan_payload, ensure_ascii=False, default=str)[:8000]
        )
        raw = model.invoke(
            [
                SystemMessage(content=REVIEWER_SYSTEM),
                HumanMessage(content=user),
            ]
        )
        data = _parse_llm_json(message_text(raw))
        obs = data.get("observations") or []
        return [str(o).strip() for o in obs if str(o).strip()][:3]
    except Exception:  # noqa: BLE001 — compliance caído/LLM no debe tumbar el servicio
        return []


def review_plan(plan_payload: dict[str, Any]) -> dict[str, Any]:
    """Combina reglas + LLM. Nunca lanza: degradá a solo reglas si hace falta."""
    rule_obs = apply_compliance_rules(plan_payload)
    llm_obs = _invoke_llm(plan_payload)
    # Dedup preservando orden
    seen: set[str] = set()
    merged: list[str] = []
    for o in rule_obs + llm_obs:
        key = o.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged.append(o)
    approved = len(merged) == 0
    return {
        "approved": approved,
        "observations": merged,
        "skill": "review_plan",
    }
