"""Nodo A2A: revisión consultiva del plan (no bloqueante)."""

from __future__ import annotations

from portfoliosentinel.graph.logging_utils import get_node_logger, log_json
from portfoliosentinel.graph.state import PortfolioState

logger = get_node_logger("portfoliosentinel.graph.nodes_a2a")


def a2a_compliance_node(state: PortfolioState) -> dict:
    """Envía el plan aprobado al servicio A2A. Si está caído → marca unavailable."""
    # Import diferido: evita ciclo graph.__init__ → builder → nodes_a2a → a2a_client → graph.
    from portfoliosentinel.tools.a2a_client import UNAVAILABLE_MSG, review_plan_via_a2a

    run_id = state.get("run_id", "")
    plan = state.get("plan")
    review = review_plan_via_a2a(
        plan,
        constraints=list(state.get("constraints") or []),
        diagnosis=state.get("diagnosis"),
    )
    log_json(
        logger,
        "a2a_review_done",
        run_id=run_id,
        available=review.available,
        approved=review.approved,
        n_observations=len(review.observations),
        summary=review.summary or (UNAVAILABLE_MSG if not review.available else "ok"),
    )
    return {"a2a_review": review}
