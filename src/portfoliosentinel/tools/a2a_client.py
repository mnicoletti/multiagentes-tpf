"""Cliente A2A no bloqueante (ADR-0008)."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

from portfoliosentinel.graph.state import (
    Constraint,
    Diagnosis,
    ExternalReview,
    RebalancePlan,
)

DEFAULT_A2A_BASE = os.environ.get("A2A_BASE_URL", "http://127.0.0.1:8765")
UNAVAILABLE_MSG = "revisión externa no disponible"


def a2a_base_url() -> str:
    return os.environ.get("A2A_BASE_URL", DEFAULT_A2A_BASE).rstrip("/")


def build_plan_payload(
    plan: RebalancePlan | None,
    *,
    constraints: list[Constraint] | None = None,
    diagnosis: Diagnosis | None = None,
) -> dict[str, Any]:
    restricted = [
        c.ticker.upper()
        for c in (constraints or [])
        if c.status == "active" and c.confirmed and c.ticker
    ]
    cluster_weights: list[dict[str, Any]] = []
    if plan and plan.calculator_result:
        resulting = plan.calculator_result.get("resulting_cluster_weights") or []
        if isinstance(resulting, list):
            cluster_weights = [r for r in resulting if isinstance(r, dict)]
    if not cluster_weights and diagnosis is not None:
        cluster_weights = [
            {"name": c.name, "weight": str(c.weight), "tickers": list(c.tickers)}
            for c in diagnosis.clusters
        ]
    actions = []
    if plan is not None:
        for a in plan.actions:
            actions.append(
                {
                    "ticker": a.ticker,
                    "action": a.action,
                    "quantity": str(a.quantity) if a.quantity is not None else None,
                    "stop_level": str(a.stop_level) if a.stop_level is not None else None,
                }
            )
    return {
        "actions": actions,
        "cluster_weights": cluster_weights,
        "restricted_tickers": restricted,
        "notes": (plan.notes if plan else "") or "",
    }


def _parse_review_from_task(task: dict[str, Any]) -> ExternalReview:
    observations: list[str] = []
    approved = True
    for art in task.get("artifacts") or []:
        if not isinstance(art, dict):
            continue
        for part in art.get("parts") or []:
            if not isinstance(part, dict):
                continue
            data = part.get("data")
            if isinstance(data, dict):
                approved = bool(data.get("approved", True))
                observations = [str(o) for o in (data.get("observations") or [])]
                break
    if not observations:
        status = task.get("status") or {}
        msg = status.get("message") or {}
        for part in msg.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "text":
                text = part.get("text") or ""
                try:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        approved = bool(data.get("approved", True))
                        observations = [str(o) for o in (data.get("observations") or [])]
                except json.JSONDecodeError:
                    if text.strip():
                        observations = [text.strip()]
    return ExternalReview(
        available=True,
        approved=approved and not observations,
        observations=observations,
        summary="ok" if (approved and not observations) else "observations",
    )


def review_plan_via_a2a(
    plan: RebalancePlan | None,
    *,
    constraints: list[Constraint] | None = None,
    diagnosis: Diagnosis | None = None,
    timeout_s: float | None = None,
) -> ExternalReview:
    """Llama al servicio A2A. Si está caído / timeout → unavailable (no lanza)."""
    if timeout_s is None:
        timeout_s = float(os.environ.get("A2A_TIMEOUT_S", "8"))
    base = a2a_base_url()
    payload = build_plan_payload(plan, constraints=constraints, diagnosis=diagnosis)
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": json.dumps({"skill": "review_plan", "plan": payload}),
                    }
                ],
            },
            "metadata": {"skill": "review_plan", "plan": payload},
            "configuration": {"blocking": True, "acceptedOutputModes": ["application/json"]},
        },
    }
    try:
        with httpx.Client(timeout=timeout_s) as client:
            # Discovery opcional (Agent Card); si falla, igual intentamos RPC.
            try:
                card = client.get(f"{base}/.well-known/agent.json")
                card.raise_for_status()
            except Exception:  # noqa: BLE001
                pass
            resp = client.post(f"{base}/a2a", json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — degradación obligatoria ADR-0008
        return ExternalReview(
            available=False,
            approved=False,
            observations=[UNAVAILABLE_MSG],
            summary=UNAVAILABLE_MSG,
        )

    if not isinstance(data, dict) or "error" in data:
        return ExternalReview(
            available=False,
            approved=False,
            observations=[UNAVAILABLE_MSG],
            summary=UNAVAILABLE_MSG,
        )
    result = data.get("result")
    if not isinstance(result, dict):
        return ExternalReview(
            available=False,
            approved=False,
            observations=[UNAVAILABLE_MSG],
            summary=UNAVAILABLE_MSG,
        )
    return _parse_review_from_task(result)


def format_a2a_section(review: ExternalReview | None) -> str:
    """Bloque markdown anexado al informe (consultivo; no es sección §6.3)."""
    lines = ["", "## Revisión externa (A2A)", ""]
    if review is None or not review.available:
        msg = UNAVAILABLE_MSG
        if review and review.observations:
            msg = review.observations[0]
        lines.append(f"- {msg}")
        lines.append("- Las restricciones del usuario las aplica el validator interno.")
        return "\n".join(lines)
    if not review.observations:
        lines.append("- Veredicto consultivo: sin observaciones.")
    else:
        lines.append("- Observaciones consultivas (no bloquean el informe):")
        for obs in review.observations:
            lines.append(f"  - {obs}")
    lines.append("- Las restricciones del usuario las aplica el validator interno.")
    return "\n".join(lines)
