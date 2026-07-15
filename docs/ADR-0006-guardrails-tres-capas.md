# ADR-0006: Guardrails en tres capas, deterministas en los bordes

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
El enunciado exige análisis de prompt injection, jailbreak, datos sensibles y templates de guardrails. El dominio agrava el riesgo: datos financieros personales reales y recomendaciones con números que un LLM puede alucinar.

## Decision Drivers
- Lo verificable se verifica con código (coherente con [[ADR-0002-frontera-agente-determinista]]).
- PII real jamás en contexto LLM, BD ni repo.
- Templates parametrizables = ítem literal de rúbrica con valor operativo.

## Options Considered
**A. Guardrails solo por prompt** — probabilísticos donde el riesgo es numérico/legal; insuficiente.
**B. Framework de guardrails de terceros** — dependencia extra y curva de aprendizaje para reglas que son ifs.
**C. Tres capas propias, deterministas en entrada y salida** — elegida.

## Decision
- **Entrada (determinista):** validación estructural del `.xlsx` (totales vs suma de filas); rechazo limpio de malformados antes de cualquier LLM; **scrubbing de PII** (titular/comitente → alias `INV-001`).
- **Prompts (probabilística):** separación instrucción/dato; imágenes, resultados web y texto RAG envueltos como dato no confiable. Vectores documentados: injection en resultados de búsqueda e injection en texto incrustado en imágenes.
- **Salida (determinista):** linter de informe con reglas como **templates YAML**: hard constraints (no vender restringidos), cantidad ≤ tenencia del snapshot, descargo presente, sin lenguaje de ejecución, estructura de 7 secciones. Rechazo → re-ruteo al Planificador con feedback (máx. 2 reintentos → HITL).
- **Datos:** repo solo con **fixture sintética**; archivos reales quedan locales del usuario. Auth multiusuario fuera de scope (trabajo futuro, sistema single-user local).

## Consequences
- (+) El guardrail estrella (restricciones) es testeable y es además el golden case GC-2.
- (+) Sección 6 del informe académico se escribe con hechos, no con promesas.
- (−) El linter exige formato de salida parseable del Redactor — resuelto con secciones marcadas.

**Trazabilidad rúbrica:** "Guardrails. Consideraciones de seguridad mínima"; "Templates para GuardRail"; "manejo de datos sensibles"; "Prompt Injection".
