"""Agent Card A2A (SPEC §11 / ADR-0008) — única skill: review_plan."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_HOST = os.environ.get("A2A_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("A2A_PORT", "8765"))


def base_url(host: str | None = None, port: int | None = None) -> str:
    h = host or DEFAULT_HOST
    p = port if port is not None else DEFAULT_PORT
    return f"http://{h}:{p}"


def build_agent_card(*, host: str | None = None, port: int | None = None) -> dict[str, Any]:
    url = base_url(host, port)
    return {
        "name": "BrokerComplianceReviewer",
        "description": (
            "Agente de compliance consultivo de un bróker externo (simulado). "
            "Revisa planes de rebalanceo contra reglas de concentración y "
            "perfil; no bloquea ni ejecuta órdenes (ADR-0008)."
        ),
        "url": f"{url}/a2a",
        "provider": {
            "organization": "PortfolioSentinel Demo Broker (ficticio)",
            "url": url,
        },
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "defaultInputModes": ["application/json", "text/plain"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "review_plan",
                "name": "Review rebalance plan",
                "description": (
                    "Recibe un plan de rebalanceo (acciones, clusters, restricciones) "
                    "y devuelve approved u observations consultivas."
                ),
                "tags": ["compliance", "portfolio", "consultivo"],
                "examples": [
                    "Revisá este plan: no vender YPFD; reducir GGAL con stop.",
                ],
                "inputModes": ["application/json"],
                "outputModes": ["application/json"],
            }
        ],
    }
