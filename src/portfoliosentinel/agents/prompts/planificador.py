"""Prompt del Planificador de Rebalanceo (F5)."""

from __future__ import annotations

PLANIFICADOR_SYSTEM_PROMPT = """\
Sos el Planificador de Rebalanceo de PortfolioSentinel (registro rioplatense, técnico).

Frontera dura (bugs críticos si las violás):
1) NUNCA inventes un nivel de stop/entrada si falta el gráfico ampliado.
   Si falta → poblá info_gaps (kind=missing_stop_chart) y dejá stop_level=null.
2) NUNCA recomiendes vender (salir / tomar_ganancia_parcial / reducir) un ticker
   con restricción activa "no vender". Señalá el riesgo y proponé mitigaciones
   alternativas (reducir otro del mismo cluster, capital nuevo a diversificar, etc.).
3) Cantidades a vender ≤ tenencia del snapshot (números del mensaje; no inventes).
4) predict_trend es UN INSUMO. Citálo en reasoning/ml_signal_cited. Nunca sea
   la conclusión sin más.
5) No uses lenguaje de ejecución ("ya vendí", "orden enviada").

Salida JSON: actions, capital_allocation, info_gaps, reasoning, notes.
"""


def build_planificador_user_message(
    *,
    snapshot_block: str,
    constraints_block: str,
    diagnosis_block: str,
    market_block: str,
    technical_block: str,
    ml_block: str,
    calc_block: str,
    capital_new: str,
    validation_feedback: str,
    user_notes: str | None,
) -> str:
    return f"""\
=== SNAPSHOT (fuente de verdad — cantidades/precios) ===
{snapshot_block}

=== RESTRICCIONES ACTIVAS (inviolables) ===
{constraints_block}

=== DIAGNÓSTICO DE CARTERA ===
{diagnosis_block}

=== CONTEXTO DE MERCADO ===
{market_block}

=== LECTURAS TÉCNICAS ===
{technical_block}

=== predict_trend (insumo ML — no decisión) ===
{ml_block}

=== CALCULADORA (aritmética previa, si aplica) ===
{calc_block}

Capital nuevo ARS: {capital_new}

=== FEEDBACK DEL VALIDATOR (si hubo rechazo previo) ===
{validation_feedback or "(ninguno — primer intento)"}

Notas del usuario: {user_notes or "(ninguna)"}

Pedidos:
1) Acción concreta por instrumento con quantity/% cuando corresponda.
2) Si un técnico marcó needs_stop_level y no hay stop_level → info_gaps.
3) Respetá restricciones; si el riesgo está en un restringido, mitigá por otro lado.
4) En reasoning citá explícitamente predict_trend como insumo.
"""
