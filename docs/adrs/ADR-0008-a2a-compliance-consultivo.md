# ADR-0008: A2A — agente de compliance externo, consultivo y no bloqueante

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
La rúbrica (contenidos medios) pide simular comunicación A2A con un agente de otra organización. En un sistema que no ejecuta órdenes, el rol externo debe inventarse con verosimilitud y sin construir un segundo sistema. Es, por diseño, **el único ítem descartable** si el cronograma aprieta ([[PLAN-implementacion]] F8).

## Decision Drivers
- Chico, creíble, explicable en dos frases.
- La gracia está en el **protocolo** (proceso separado, Agent Card, tasks), no en la inteligencia del agente.
- La demo no puede morir por un servicio auxiliar.

## Options Considered
**A. Mesa de research externa (provee contexto)** — se solapa con el Analista de Mercado; confunde responsabilidades.
**B. Agente ejecutor de órdenes** — contradice la restricción de negocio "no ejecuta".
**C. Compliance del bróker, consultivo** — elegida: en el mundo real un bróker valida planes contra el perfil del inversor.

## Decision
- Proceso separado (FastAPI): Agent Card en `/.well-known/agent.json` con única skill `review_plan`; endpoint de tasks del protocolo A2A.
- PortfolioSentinel envía el plan aprobado por el validator como task; respuesta `approved` u `observations` (ej. concentración sectorial excedida). Internamente: un LLM call con prompt de revisor + 2–3 reglas.
- Las observaciones **se anexan al informe como "revisión externa", no bloquean** — el tercero es consultivo; las restricciones del usuario las aplica el validator interno.
- **Degradación:** servicio caído → el grafo sigue y el informe marca "revisión externa no disponible".

## Consequences
- (+) Ítem A2A cubierto con protocolo real y rol de dominio verosímil.
- (+) Respuestas de examen preparadas: por qué no bloquea, por qué proceso separado.
- (−) Un servicio más que levantar en la demo — mitigado por la degradación y por el `make a2a`.

**Trazabilidad rúbrica:** "Protocolo A2A — simular comunicación con agente de otra organización".
