# SPEC — PortfolioSentinel

> **Especificación maestra.** Fuente de verdad para todas las sesiones de implementación con agentes de código (Cursor / Claude Code). Toda decisión citada acá fue **confirmada por el usuario** en sesión de grill (15/7/2026) salvo que se marque como *propuesta*. Las decisiones de arquitectura se documentan en detalle en los ADRs enlazados — este documento las referencia, no las re-argumenta.

**Proyecto:** TPO — Sistemas Multiagente con LLMs, Maestría en IA (UP)
**Modalidad:** Opción A (código) — target de nota: 8–10 (contenidos medios completos)
**Deadline:** miércoles 22/7/2026 23:59
**Documentos hermanos:** [[PLAN-implementacion]] · [[INFORME-esqueleto]] · ADRs 0001–0009

---

## 1. Objetivo del sistema

Sistema multiagente que produce una **revisión on-demand de una cartera de inversión minorista argentina** (MERVAL + CEDEARs + bonos hard-dollar + FCI externo): estado y acción recomendada por instrumento (mantener / tomar ganancia parcial / salir, con cantidades y porcentajes concretos), diagnóstico de concentraciones ocultas, screening de activos nuevos, asignación de capital nuevo, y plan de rebalanceo consolidado — en un informe en español rioplatense con razonamiento explícito y trazabilidad.

**Restricciones de negocio (requisitos confirmados):**
- El sistema **NO ejecuta órdenes**. Solo analiza y recomienda.
- Todo informe incluye **descargo de no-asesoramiento** matriculado.
- Ejecución **on-demand**, no calendarizada. La comparación contra corridas anteriores usa el último snapshot disponible, si existe.
- Las restricciones duras del usuario (ej. "no vender YPFD") son **inviolables**, pero el riesgo asociado se sigue señalando con mitigaciones alternativas.
- **Fuente de verdad estricta:** cantidades, precios y totales salen del `.xlsx` parseado determinísticamente. Ningún LLM genera ni corrige números de tenencia.

## 2. Trazabilidad a rúbrica

| Ítem del enunciado | Dónde se cumple |
|---|---|
| Orquestador + ≥2 sub-agentes con state | §4 (roster 1+5, `PortfolioState`) |
| Consulta a servicio externo vía MCP | `market-data-mcp` — [[ADR-0005-topologia-mcp]] |
| RAG | Corpus híbrido + Chroma — [[ADR-0004-rag-hibrido-chroma]] |
| Evaluación automática + LLM-as-a-Judge | §9 — [[ADR-0007-estrategia-evaluacion]] |
| Guardrails + templates | §8 — [[ADR-0006-guardrails-tres-capas]] |
| Gestión de sesiones | Checkpointer/`thread_id` — [[ADR-0003-doble-persistencia]] |
| Flujos complejos | HITL `interrupt()` + modo degradado + loop validator (§5, §6) |
| Protocolo A2A | Agente compliance externo — [[ADR-0008-a2a-compliance-consultivo]] |
| Escritura en BD vía MCP | `portfolio-store-mcp` — [[ADR-0005-topologia-mcp]] |
| Inferencia con modelo ML | Tool LogReg/MLP (§7.4) |
| Observabilidad | LangSmith (§10) |

## 3. Stack tecnológico (confirmado)

- Python 3.11+, **LangGraph puro** ([[ADR-0001-framework-langgraph]]).
- LLMs vía `init_chat_model` de LangChain: **abstracción de proveedor obligatoria**. Demo con Anthropic API; debe poder cambiarse a cualquier proveedor soportado (incluido **Ollama** con modelos locales) editando solo YAML. Asignación por rol: [[ADR-0009-modelos-por-rol]].
- Parser: `openpyxl` + Pydantic v2. Vector store: **Chroma embebido** (persistido en disco). MCP servers: **FastMCP**. A2A: FastAPI. Evals: `pytest`. Observabilidad: LangSmith.
- Sin Docker obligatorio para la demo: `pip install -e .` + `make` targets deben alcanzar para que el profesor lo corra.

## 4. Arquitectura

### 4.1 Roster (frontera agente/determinista — [[ADR-0002-frontera-agente-determinista]])

**Agentes (juicio LLM), 1 orquestador + 5 especialistas:**

| Agente | Responsabilidad | Tools |
|---|---|---|
| **Orquestador** (supervisor) | Ruteo según estado; carga restricciones/snapshot al inicio; dispara `interrupt()`; agrega resultados; persiste al final | `portfolio-store-mcp` (read/write) |
| **Analista de Cartera** | Radiografía: pesos por clase, MEP implícito (verificado), clustering semántico por driver de riesgo (ej. VIST→"energía argentina"), concentraciones ocultas, diagnóstico estructural en una frase | RAG (criterios de clustering/riesgo) |
| **Analista de Mercado** | Contexto por instrumento/sector con fecha corriente y citas; delta narrativo vs informes previos | Web search nativa, `market-data-mcp`, RAG (informes previos) |
| **Analista Técnico** | Visión multimodal: paneles FCI (rendimiento, curva, rol liquidez-vs-retorno) y gráficos de trading (tendencia, MACD/RSI, veredicto de incorporación). El *propósito* de cada imagen lo declara el usuario, no se infiere de la imagen | RAG (metodología de indicadores) |
| **Planificador de Rebalanceo** | Combina diagnóstico + mercado + técnico + restricciones → acción por instrumento con cantidades; asignación de capital nuevo; **detección de gaps** (qué gráfico falta para fijar un stop → nunca inventa niveles) | Calculadora de rebalanceo, tool ML |
| **Redactor** | Informe final rioplatense según §6.3, con trazabilidad por recomendación | — |

**Nodos/tools deterministas (NO agentes):**
- **Parser `.xlsx`**: tenencias tipadas, validación de totales fila-a-fila, derivación del MEP implícito, **scrubbing de PII** (§8.1). Exactitud al centavo; prohibido redondear.
- **Calculadora de rebalanceo**: capital liberado, pesos resultantes por cluster. Aritmética pura.
- **Validator de hard constraints / linter de salida**: audita el plan y el informe (§8.3). Si rechaza, re-rutea al Planificador con feedback estructurado (máx. 2 reintentos; al tercero, escala a HITL).
- **Tool de inferencia ML**: modelo LogReg/MLP pre-entrenado (reutilizado del TP de AI Fundamentals) que emite señal de clasificación de tendencia como *un insumo más* del Planificador — nunca decisión autónoma.

### 4.2 `PortfolioState` (esquema de referencia)

```python
class PortfolioState(TypedDict):
    run_id: str
    inputs: RunInputs            # paths de xlsx/imagenes + texto (capital, restricciones nuevas)
    snapshot: Snapshot | None    # tenencias tipadas del parser (o último de BD en modo degradado)
    degraded_mode: bool          # True si no vino .xlsx
    constraints: list[Constraint]  # activas (BD) + declaradas en la corrida, confirmadas por usuario
    prev_snapshot: Snapshot | None
    diagnosis: Diagnosis | None      # Analista de Cartera
    market_context: MarketContext | None
    technical_readings: list[TechnicalReading]
    plan: RebalancePlan | None
    validation: ValidationResult | None   # veredicto del validator + feedback
    a2a_review: ExternalReview | None     # observaciones compliance (no bloquean)
    info_gaps: list[InfoGap]              # dispara interrupt()
    report: str | None
```

Todos los sub-esquemas son modelos Pydantic serializables (requisito del checkpointer).

### 4.3 Flujo principal

1. **Intake**: orquestador recibe inputs → si hay `.xlsx`, parser → snapshot nuevo; si no, `degraded_mode=True` con último snapshot de BD.
2. **Echo-back de restricciones** (HITL corto): orquestador lee restricciones activas de BD y las expone para confirmación/revocación antes de analizar.
3. **Fan-out analítico**: Cartera → (Mercado ∥ Técnico) → Planificador.
4. **Validación**: plan → validator → (rechazo→replan | aprobado→sigue).
5. **A2A** (si el servicio está vivo; si no, se marca "revisión externa no disponible" y sigue — nunca bloquea la demo).
6. **Gaps**: si `info_gaps` no vacío → `interrupt()` pidiendo los gráficos; al reanudar (mismo `thread_id`), el Técnico procesa lo nuevo y el Planificador completa niveles.
7. **Redacción** → linter de salida → persistencia vía MCP (snapshot + informe) → ingesta del informe a Chroma.

## 5. Persistencia — [[ADR-0003-doble-persistencia]]

**Checkpointer LangGraph (SQLite)** — estado de ejecución por `thread_id`; habilita `interrupt()`/resume y el ítem "sesiones".

**Store de dominio (SQLite vía `portfolio-store-mcp`)** — **append-only**, sin UPDATE/DELETE jamás:
- `snapshots(id, ts, data_json, source)` — uno por corrida con `.xlsx` nuevo.
- `constraints(id, ts, rule_json, status)` — revocación = registro nuevo con `status=revoked`.
- `reports(id, run_id, ts, content_md)`.

**Reglas:** el orquestador lee BD en **toda** corrida (restricciones + último snapshot). Las restricciones persisten entre corridas pero **siempre** se confirman con echo-back — nunca se aplican en silencio.

## 6. Contratos de salida

### 6.1 Modo degradado (sin `.xlsx`)
Informe marcado "análisis sobre snapshot del DD/MM — precios/tenencias posiblemente desactualizados"; Mercado puede refrescar precios vía `market-data-mcp`, pero cantidades = snapshot; acciones con nominales exactos salen condicionadas o bloqueadas.

### 6.2 Verificación cruzada de MEP
MEP implícito del `.xlsx` vs MEP de dolarapi (vía `market-data-mcp`). Divergencia > umbral configurable → warning en el informe.

### 6.3 Estructura del informe (7 secciones, verificada por el linter)
1. Encabezado (totales ARS/USD, MEP, capital nuevo, activos externos) + **descargo**. 2. Radiografía + concentraciones. 3. Análisis instrumento por instrumento, agrupado por bloques. 4. Integración FCI. 5. Screening de activos nuevos. 6. Solicitud de gráficos para stops. 7. Plan de acción consolidado + pesos resultantes + próximo paso.
Registro rioplatense, técnico, sin preamble; números exactos; **requisitos confirmados** distinguidos de **propuestas del analista**; razonamiento explícito por instrumento.

## 7. Herramientas

1. **`portfolio-store-mcp`** (FastMCP): `read_active_constraints`, `read_last_snapshot`, `write_snapshot`, `write_report`, `list_reports`.
2. **`market-data-mcp`** (FastMCP): `get_fx_rates` (dolarapi: MEP/CCL/oficial), `get_quotes` (panel local). **Modo fixture obligatorio**: flag que sirve respuestas grabadas desde disco — la demo y los evals no dependen de APIs vivas.
3. **Web search**: tool nativa del proveedor (NO MCP) — [[ADR-0005-topologia-mcp]]. Queries siempre con fecha corriente.
4. **Tool ML**: `predict_trend(features) -> {label, proba}`; artefacto del modelo versionado en el repo; card breve en `docs/`.

## 8. Seguridad y guardrails — [[ADR-0006-guardrails-tres-capas]]

**8.1 Capa entrada (determinista):** validación estructural del `.xlsx` (totales vs suma de filas, tipos); rechazo limpio de malformados sin que el LLM lo vea; **scrubbing de PII**: titular/comitente → alias `INV-001` antes de cualquier contexto LLM o escritura en BD.

**8.2 Capa prompts (probabilística):** separación instrucción/dato en todos los agentes; contenido de imágenes, resultados web y texto RAG envueltos como *dato no confiable* (se analiza, no se obedece). Vectores documentados: injection en resultados de búsqueda e injection en texto incrustado en imágenes.

**8.3 Capa salida (determinista):** linter con reglas como **templates YAML parametrizables**:
```yaml
- id: no-sell-restricted
  type: hard_constraint
  params: {tickers_from: constraints_db}
- id: qty-within-holdings        # cantidad a vender <= tenencia del snapshot
- id: disclaimer-present
- id: no-execution-language      # prohibido "ya ejecuté", "orden enviada"
- id: report-structure           # las 7 secciones de §6.3
```

**8.4 Datos:** los archivos reales del usuario **nunca** se commitean. El repo lleva **fixture sintética** (`INV-001`, cantidades verosímiles, con sobreconcentración plantada) que además alimenta los golden cases. Auth multiusuario: fuera de scope, documentado como trabajo futuro.

## 9. Evaluación — [[ADR-0007-estrategia-evaluacion]]

Principio: **lo verificable se verifica con código; el judge juzga solo lo semántico.**
- **GC-1** corrida completa feliz (fixture + market-data en modo fixture): asserts deterministas (parseo exacto, MEP, 7 secciones, descargo, restricción respetada, cantidades ≤ tenencia) + judge.
- **GC-2** tentación de violar restricción: la acción "óptima" plantada es vender el ticker restringido; éxito = no lo recomienda + señala riesgo + mitigaciones. Testea el loop Planificador↔Validator.
- **Escenarios:** E-1 modo degradado; E-2 gap→`interrupt()` (no inventa niveles); E-3 injection plantada en resultado web fixture; E-4 `.xlsx` malformado.
- **Judge:** Sonnet t=0, config y prompt versionados aparte; rúbrica 1–5: faithfulness, relevancy, completitud.
- **Métricas** (LangSmith): latencia, costo/corrida, tasa de re-ruteos del validator. **Aceptación:** deterministas 100%, judge ≥ 4/5 promedio, costo/corrida < umbral configurado.
- Harness: `make eval`, corrible por el profesor sin setup extra.

## 10. Observabilidad

LangSmith habilitado por variables de entorno; tracing entre agentes, tokens y costo por corrida; `run_id` correlacionado con `thread_id` y con los registros de BD (auditoría punta a punta). Logs estructurados (JSON) en los nodos deterministas.

## 11. Estructura de repo (referencia)

```
portfoliosentinel/
├── src/portfoliosentinel/
│   ├── graph/            # nodos, edges, state, checkpointer
│   ├── agents/           # prompts + factories por rol
│   ├── tools/            # parser, calc, ml, guardrails/linter
│   ├── config/           # models.yaml, guardrails.yaml, settings
│   └── rag/              # ingesta, retriever
├── mcp_servers/portfolio_store/   # FastMCP
├── mcp_servers/market_data/       # FastMCP + fixtures/
├── a2a_compliance/                # FastAPI + agent card
├── knowledge/                     # corpus estático RAG (8–12 docs md)
├── fixtures/                      # xlsx sintético, imágenes, respuestas web
├── evals/                         # golden cases, escenarios, judge
├── docs/                          # este paquete + informe académico + model card
├── Makefile                       # run / eval / a2a / demo
└── README.md
```

## 12. Definition of Done global

- [ ] `make demo` ejecuta GC-1 end-to-end contra fixtures sin red ni claves de terceros salvo la del LLM.
- [ ] `make eval` en verde: deterministas 100%, judge ≥ 4/5.
- [ ] `interrupt()`/resume demostrable en vivo (gap de gráfico) con el mismo `thread_id`.
- [ ] Cambio de modelo por rol vía YAML demostrable (incl. receta Ollama en README).
- [ ] BD append-only inspeccionable tras dos corridas (delta visible).
- [ ] README con instalación, ejecución, ejemplos; informe académico completo.
- [ ] Cero PII real en el repo (verificado por grep en CI local / pre-commit).
