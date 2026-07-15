# ADR-0002: Frontera agente/determinista y roster 1+5

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
El spec funcional (§6) listaba 9 capacidades. Mapear capacidad→agente produce over-engineering que la cátedra penaliza explícitamente ("cantidad de agentes vs complejidad"; exige justificar la necesidad de cada agente). Además, el requisito "fuente de verdad estricta" prohíbe que un LLM manipule cantidades.

## Decision Drivers
- Criterio único y explicable: **es agente solo si requiere juicio LLM; si es verificable/computable, es nodo o tool determinista**.
- Anti-alucinación numérica: los números nunca pasan por generación.
- Cada agente debe justificar su existencia por modalidad de input, herramientas o expertise distintos.

## Options Considered
**A. 9 agentes (mapeo literal del spec)** — infla el grafo, multiplica prompts y superficie de fallo; indefendible ante "¿por qué necesitás un agente para parsear un xlsx?".
**B. 1+4 (fusionar Cartera+Planificador)** — viable, pero pierde la separación diagnóstico/plan, que es donde el validator corta el grafo para re-rutear.
**C. 1+5 con frontera dura** — elegida.

## Decision
**Agentes:** Orquestador + Analista de Cartera, Analista de Mercado, Analista Técnico (visión), Planificador de Rebalanceo, Redactor.
**Deterministas:** parser `.xlsx` (openpyxl+Pydantic), calculadora de rebalanceo, validator de hard constraints / linter de salida, tool de inferencia ML.
La detección de gaps de información no es un agente: es responsabilidad del Planificador + `interrupt()` del framework.

## Consequences
- (+) Justificación multiagente sale sola (modalidades: texto/tabular, web, visión; expertises separadas).
- (+) Los números son testeables al centavo; el validator es código, no prompt.
- (−) La separación diagnóstico/plan agrega un hop de latencia — aceptado, medible en LangSmith.

**Trazabilidad rúbrica:** "orquestador + ≥2 sub-agentes"; "justificar la necesidad de múltiples agentes"; trade-off cantidad-vs-complejidad resuelto explícitamente.
