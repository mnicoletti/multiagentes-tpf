# PLAN de implementación — PortfolioSentinel

> Faseado para **sesiones de agente de código** (Cursor / Claude Code). Regla de mecánica: **una fase por sesión**; cada sesión arranca leyendo [[SPEC-portfoliosentinel]] + su fase + los ADRs citados; no se avanza sin el DoD de la fase en verde. Cada fase incluye un *prompt de arranque* listo para pegar.

**Hoy:** 15/7/2026 · **Entrega:** 22/7/2026 23:59
**Regla de degradación (confirmada):** si el 20/7 hay atraso, **F8 (A2A) se degrada o cae** — con F1–F7 el TPO sigue en zona 8–9. Ninguna otra fase es descartable.

| Fase | Contenido | Días sugeridos |
|---|---|---|
| F1 | Esqueleto + parser + fixture | 15–16/7 |
| F2 | Grafo mínimo end-to-end | 16/7 |
| F3 | Store MCP + restricciones + modo degradado | 17/7 |
| F4 | Mercado + market-data-mcp + RAG | 17–18/7 |
| F5 | Técnico + Planificador + ML + validator + HITL | 18–19/7 |
| F6 | Redactor + linter + informe completo | 19/7 |
| F7 | Evals + judge + LangSmith | 20/7 |
| F8 | A2A + README + informe académico + pulido | 21/7 (buffer: 22/7) |

---

## F1 — Esqueleto, parser y fixture (la fuente de verdad primero)

**Alcance:** repo según SPEC §11; config YAML (`models.yaml` por rol con provider+model vía `init_chat_model`, `settings`); parser `.xlsx` (openpyxl + Pydantic v2) con validación de totales, MEP implícito y scrubbing de PII; **fixture sintética** `fixtures/estadocuenta-sintetico.xlsx` con las 4 secciones (MONEDAS/ACCIONES/BONOS/CEDEARS), titular ficticio `INV-001`, sobreconcentración plantada en un ticker y capital coherente; tests unitarios del parser.
**ADRs:** [[ADR-0002-frontera-agente-determinista]], [[ADR-0006-guardrails-tres-capas]], [[ADR-0009-modelos-por-rol]].
**DoD:** `pytest tests/parser` verde; parseo exacto al centavo contra valores esperados hardcodeados; `.xlsx` malformado → excepción tipada con mensaje claro; grep de PII en fixture = vacío; `make lint` configurado.
**Prompt de arranque:**
> Leé `docs/SPEC-portfoliosentinel.md` (completa) y `docs/PLAN-implementacion.md` fase F1, más ADR-0002/0006/0009. Implementá exclusivamente el alcance de F1. No toques nada de fases posteriores. Al terminar, corré el DoD y reportá cada ítem como PASS/FAIL con evidencia.

## F2 — Grafo mínimo end-to-end

**Alcance:** `PortfolioState` (SPEC §4.2); grafo LangGraph con orquestador + Analista de Cartera + checkpointer SQLite; nodo parser integrado; prompt del Analista de Cartera (clustering semántico por driver, concentraciones por posición y por cluster, diagnóstico en una frase); salida por consola de la radiografía.
**DoD:** una corrida con la fixture produce radiografía con: pesos por clase, MEP, ≥1 cluster semántico correcto (el plantado), diagnóstico; el estado queda checkpointeado y es re-inspeccionable por `thread_id`; trazas visibles si LangSmith está configurado.
**Prompt de arranque:** análogo a F1, citando F2 y ADR-0001/0002/0003.

## F3 — Store de dominio MCP, restricciones y modo degradado

**Alcance:** `portfolio-store-mcp` (FastMCP) con las 5 tools de SPEC §7.1; esquema append-only §5; integración en el orquestador: lectura al inicio (siempre), **echo-back de restricciones** para confirmación, persistencia al final; `degraded_mode` cuando no hay `.xlsx` (último snapshot + marcas de staleness).
**DoD:** dos corridas consecutivas dejan 2 snapshots y 2 informes-stub en BD sin ningún UPDATE/DELETE (verificado por test que inspecciona SQLite); revocar una restricción crea registro nuevo; corrida sin `.xlsx` produce estado `degraded_mode=True` con el snapshot anterior cargado.
**Prompt de arranque:** citar F3 y ADR-0003/0005.

## F4 — Analista de Mercado, market-data-mcp y RAG

**Alcance:** `market-data-mcp` (FastMCP: `get_fx_rates`, `get_quotes`) con **modo fixture por flag** y respuestas grabadas en `fixtures/market/`; verificación cruzada MEP (SPEC §6.2); Chroma embebido + ingesta del corpus estático; **borrador de los 8–12 docs de `knowledge/`** (metodología MACD/RSI/medias, instrumentos argentinos, marco de clustering por drivers, criterios de riesgo/stops) — el agente los redacta, el usuario los valida después; Analista de Mercado con web search nativa (fecha corriente en queries), market-data y retrieval, con citas; ingesta automática de informes a Chroma al persistir.
**DoD:** con `MARKET_FIXTURE=1`, corrida sin red externa (salvo LLM) obtiene FX y quotes; divergencia de MEP plantada dispara el warning; retrieval devuelve el doc correcto ante 3 queries de prueba; el informe-stub persistido queda indexado y es recuperable.
**Prompt de arranque:** citar F4 y ADR-0004/0005. Nota explícita: los docs de `knowledge/` son borradores a validar por el humano — marcarlos con frontmatter `status: draft`.

## F5 — Técnico, Planificador, ML, validator y HITL

**Alcance:** Analista Técnico multimodal (fixtures de imágenes: 1 panel FCI + 2 gráficos de trading sintéticos o de dominio público) con el propósito de cada imagen tomado del input del usuario; tool ML `predict_trend` con artefacto LogReg/MLP versionado + card breve; calculadora de rebalanceo; Planificador (combina todo + restricciones + capital nuevo; puebla `info_gaps` cuando falta gráfico para un stop — **prohibido inventar niveles**); **validator** de hard constraints con re-ruteo (feedback estructurado, máx. 2 reintentos → escala a HITL); **`interrupt()`** para gaps con reanudación en el mismo `thread_id`.
**DoD:** GC-2 en versión manual pasa (no recomienda vender el restringido; propone mitigaciones); un gap plantado dispara `interrupt()` y la corrida se reanuda tras aportar la imagen; el rechazo del validator produce un replan visible en trazas; `predict_trend` aparece como insumo citado en el plan, nunca como decisión final.
**Prompt de arranque:** citar F5 y ADR-0002/0006.

## F6 — Redactor y linter de salida

**Alcance:** Redactor (informe completo según SPEC §6.3, rioplatense, trazabilidad por recomendación, distinción confirmado/propuesto); linter determinista con templates YAML (SPEC §8.3) integrado post-Redactor; wiring final del grafo completo.
**DoD:** corrida completa sobre fixture produce informe con las 7 secciones (verificadas por el linter, no a ojo); linter detecta y rechaza un informe adulterado de prueba por cada regla YAML; salida legible en consola y persistida en BD.
**Prompt de arranque:** citar F6 y ADR-0006.

## F7 — Evaluación y observabilidad

**Alcance:** harness pytest para GC-1, GC-2 y E-1..E-4 (SPEC §9) con todos los servicios en modo fixture; prompt del judge versionado (`evals/judge/`), Sonnet t=0, rúbrica 1–5 (faithfulness, relevancy, completitud); reporte de métricas (latencia, costo, re-ruteos) desde LangSmith o desde trazas locales; `make eval`.
**DoD:** `make eval` corre todo con un comando; deterministas 100% verde; judge ≥ 4/5 sobre GC-1/GC-2 (si no llega, iterar prompts de agentes, no bajar el umbral); métricas volcadas a un `evals/RESULTS.md` que alimenta el informe académico.
**Prompt de arranque:** citar F7 y ADR-0007.

## F8 — A2A, README e informe académico (degradable)

**Alcance:** servicio `a2a_compliance` (FastAPI): Agent Card en `/.well-known/agent.json` con skill `review_plan`, endpoint de tasks, revisor de un solo LLM call + 2–3 reglas; integración no-bloqueante (si está caído → "revisión externa no disponible"); README (instalación, ejecución, ejemplos, receta Ollama); completar [[INFORME-esqueleto]] con métricas reales de F7 y limitaciones observadas; pulido general y ensayo de la demo.
**Degradación:** si falta tiempo, entregar solo el Agent Card + cliente con el servicio mockeado, documentando en el informe qué quedó simulado — o cortar A2A por completo (decisión ya tomada en diseño: es el único ítem descartable).
**DoD:** demo ensayada de punta a punta con guion de 5 pasos (corrida feliz → restricción → interrupt/resume → eval → BD append-only); `git grep` de PII real = vacío; zip/repo final listo.
**Prompt de arranque:** citar F8 y ADR-0008.

---

## Skills sugeridas para las sesiones de código

- `engineering:testing-strategy` al arrancar F7.
- `engineering:code-review` antes de cerrar F5 y F6 (los dos puntos de mayor complejidad).
- `engineering:documentation` en F8 para README e informe.
