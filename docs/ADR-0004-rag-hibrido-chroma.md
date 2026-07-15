# ADR-0004: RAG híbrido (corpus estático + informes propios) con Chroma embebido

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
La rúbrica exige RAG. Un RAG sin corpus con propósito real es detectable como "puesto para cumplir". El profesor debe poder ejecutar desde cero (`pip install` y nada más).

## Decision Drivers
- Demostrable desde la corrida uno (sin cold start).
- Justificación de diseño genuina, no ceremonial.
- Cero infraestructura adicional para el evaluador.

## Options Considered
**A. Solo informes previos generados** — elegante (memoria de largo plazo), pero cold start letal: en la primera corrida el corpus está vacío y el ítem no se ve.
**B. Solo base de conocimiento estática** — funciona siempre, pero desaprovecha la historia del sistema.
**C. Bibliografía de la cátedra como corpus** — descartada: material sobre agentes, sin rol en el dominio financiero.
**D. Híbrido A+B** — elegida.

## Decision
- **Corpus estático versionado en repo** (`knowledge/`, 8–12 docs md): metodología de indicadores técnicos, instrumentos argentinos (CEDEARs, bonos, MEP/CCL), marco de clustering por drivers de riesgo, criterios de gestión de riesgo/stops. Justificación central: **saca conocimiento metodológico del prompt y lo pone en documentos versionables y auditables** — prompts cortos, criterio editable sin tocar código.
- **Informes propios**: se indexan automáticamente al persistirse (el write MCP dispara la ingesta); el Analista de Mercado los recupera para el delta narrativo.
- **Vector store: Chroma embebido persistido en disco** — sin servicios externos.
- Los docs de `knowledge/` los borra-drafta el agente de código (F4) y los valida el humano (`status: draft` → `approved`).

## Consequences
- (+) RAG operativo y explicable en dos frases; el criterio de inversor queda plasmado como asset versionado.
- (−) Escribir/validar el corpus es trabajo real (~8–12 docs) — acotado por generación asistida.
- (−) Chroma embebido no escala multiusuario — irrelevante para el scope; anotado en Limitaciones.

**Trazabilidad rúbrica:** "RAG" (mínimos); "recuperación de información"; decisión de diseño justificada.
