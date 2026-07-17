# ADR-0003: Doble persistencia — checkpointer vs store de dominio append-only

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill)

## Context
El sistema necesita (a) pausar/reanudar una corrida (HITL) y (b) memoria de negocio entre corridas on-demand: snapshots de cartera, restricciones duras persistentes, informes históricos. Son ciclos de vida distintos.

## Decision Drivers
- No mezclar estado de ejecución con estado de dominio.
- Trazabilidad total (requisito del spec) y delta entre corridas.
- Cubrir "escritura en BD vía MCP" con algo con propósito real.
- Restricciones que persisten sin re-declararse, pero jamás aplicadas en silencio.

## Options Considered
**A. Solo checkpointer** — el estado de negocio quedaría atado a threads de ejecución; sin historia consultable; sin ítem MCP-write.
**B. Una sola BD mutable (CRUD)** — updates/deletes destruyen trazabilidad y el delta histórico.
**C. Doble persistencia, dominio append-only** — elegida.

## Decision
- **Checkpointer LangGraph (SQLite):** estado de una corrida por `thread_id`; habilita `interrupt()`/resume.
- **Store de dominio (SQLite vía `portfolio-store-mcp`), append-only:** `snapshots`, `constraints` (revocación = registro nuevo), `reports`. Sin UPDATE/DELETE.
- El orquestador **lee la BD en toda corrida** (restricciones + último snapshot) y hace **echo-back de restricciones** para confirmación al inicio.
- Sin `.xlsx` adjunto: **modo degradado explícito** sobre el último snapshot, con marcas de staleness y bloqueo/condicionamiento de cantidades finas — nunca rechazo silencioso ni análisis sin advertencia.

## Consequences
- (+) Historia auditable; delta mes-a-mes gratis; demo del ítem MCP-write con datos reales del dominio.
- (+) UX: "no vendo YPFD" se declara una vez y se confirma en cada corrida.
- (−) Dos SQLite que mantener sincronizadas conceptualmente (run_id ↔ registros) — mitigado correlacionando ids en trazas.

**Trazabilidad rúbrica:** "gestión de sesiones"; "escribir en BD vía MCP"; "uso de state"; flujo complejo (modo degradado).
