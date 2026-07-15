# ADR-0001: LangGraph puro como framework de orquestación

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
El TPO exige LangGraph o Google ADK (combinables). El diferencial del sistema es el flujo HITL (pausar para pedir gráficos, reanudar sesión) y la defensa es oral sobre la implementación.

## Decision Drivers
- Madurez del human-in-the-loop y del checkpointing.
- Ítem de rúbrica "gestión de sesiones" al menor costo.
- Kilometraje previo del autor (defensa oral).
- Observabilidad sin instrumentación manual.

## Options Considered
**A. LangGraph puro** — `interrupt()` + checkpointer nativos; sesiones por `thread_id` gratis; LangSmith con una env var; stack ya conocido.
**B. Google ADK** — modelo agentes-como-clases prolijo para A2A; HITL menos maduro/documentado.
**C. Combinación** — suma complejidad y superficie de preguntas sin sumar nota; la rúbrica premia justificar, no acumular frameworks.

## Decision
**Opción A: LangGraph puro.** El HITL es el corazón del sistema y se construye sobre la primitiva más sólida.

## Consequences
- (+) `interrupt()`/resume y sesiones resueltos por el framework; tracing inmediato.
- (+) Defensa sobre terreno dominado.
- (−) A2A se implementa a mano (FastAPI) en lugar de apoyarse en ADK — aceptado, ver [[ADR-0008-a2a-compliance-consultivo]].
- Revisitar solo si un requisito de A2A avanzado apareciera (no es el caso).

**Trazabilidad rúbrica:** framework permitido; "gestión de sesiones"; "flujos complejos"; decisión de diseño justificada (§9 del enunciado).
