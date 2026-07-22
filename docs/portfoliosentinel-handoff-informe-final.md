# Handoff — PortfolioSentinel: informe PDF + presentación de examen final

**Fecha:** 2026-07-21  
**Destinatario:** modelo Claude (u otro) que redacte el PDF académico y prepare el guion de defensa oral.  
**Repo:** `/Users/salvorkun/Documents/proyectos/private/git-repos/college/multiagentes-tpf`  
**Fase:** F8 cierre (E2E con xlsx real + README de uso + artefactos de entrega).

---

## Objetivo de la próxima sesión

Producir:

1. **PDF del informe final** (Opción A del enunciado / TPO multiagentes), listo para entregar.
2. **Guion de presentación oral** (~10–15 min) tipo examen: arquitectura, demo, trade-offs, límites.
3. **Diapositivas o outline** alineadas al PDF (opcional pero recomendable).

**No reimplementar el sistema.** Partí de los artefactos versionados y de la evidencia E2E abajo.

---

## Fuentes canónicas (no duplicar; citar)

| Artefacto | Path | Uso en el PDF |
|---|---|---|
| SPEC | `docs/SPEC-portfoliosentinel.md` | Requisitos, roster, §6.3 estructura informe usuario |
| PLAN | `docs/PLAN-implementacion.md` | Fases F1–F8, DoD F8 |
| ADRs Accepted | `docs/adrs/ADR-0001` … `ADR-0009` | Decisiones y trade-offs |
| ADR Proposed | `docs/adrs/ADR-0010-parser-multi-layout.md` | Parser multi-layout + totales bróker |
| Informe esqueleto (ya redactado) | `docs/INFORME-esqueleto.md` | **Base principal del PDF** — expandir/pulir, no reescribir de cero |
| Evals F7 | `evals/RESULTS.md` | Métricas GATE-F7 |
| README usuario | `README.md` | Cómo se corre (xlsx propio, modelos, imágenes) |
| Código grafo | `src/portfoliosentinel/graph/` | Diagrama de flujo real |
| Parser | `src/portfoliosentinel/tools/parser.py` | Frontera determinista |
| A2A | `a2a_compliance/` | Compliance consultivo |
| Core rules | `.cursor/rules/00-core.mdc` | Invariantes (no contradecir) |

---

## Estado del sistema (qué quedó construido)

### Arquitectura

- **Orquestador** (LangGraph) + **5 agentes**: Cartera, Mercado, Técnico (visión), Planificador, Redactor.
- **Deterministas:** parser `.xlsx`, calculadora de pesos/rebalanceo, validator/linter (`config/guardrails.yaml`), tool ML `predict_trend`.
- **Persistencia doble (ADR-0003):** checkpointer SQLite (HITL/`thread_id`) ≠ store de dominio append-only vía MCP `portfolio-store`.
- **MCP:** `portfolio-store-mcp`, `market-data-mcp` (fixture o live).
- **RAG híbrido:** Chroma (knowledge estático + informes propios).
- **A2A:** FastAPI + Agent Card `review_plan`, **consultivo y no bloqueante** (ADR-0008).
- **Modelos por rol:** YAML + `init_chat_model` (Anthropic / Gemini / Ollama) — ADR-0009.

### Diagrama de flujo (para el PDF)

Reusar el mermaid de `docs/INFORME-esqueleto.md` §2:

```
Intake+parser → Orquestador (echo-back) → Cartera → Mercado → Técnico
  → Planificador → Validator (loop ≤2 / gaps HITL)
  → A2A consultivo (degradable) → Redactor → Linter → Persist MCP+Chroma
```

Nota de implementación: la cadena analítica es **secuencial** (no fan-out paralelo) por thread-safety de Chroma `PersistentClient` — documentado en el INFORME.

### Frontera dura (mensaje de examen)

> Ningún LLM genera, corrige ni redondea cantidades/precios/totales. Salen del parser y de la calculadora. Si el modelo “calcula” un monto, es bug de diseño (ADR-0002).

---

## Hallazgos E2E con cartera real (sin PII)

**Setup:** `.xlsx` de bróker en `tmp/` (gitignored). Alias post-scrub: `INV-001`.  
**Comando:**

```bash
python -m portfoliosentinel.cli run \
  --xlsx tmp/<estado-local>.xlsx \
  --market-fixture --confirm-constraints
```

**Evidencia (corrida `e2e-real-llm`, ~205 s, Anthropic vía `models.yaml`):**

| Ítem | Resultado |
|---|---|
| Parser multi-layout | PASS — 19 posiciones, cash ARS+USD agregados, `as_of=2026-07-21` |
| Tickers nuevos sin HITL | PASS — BMA, CEPU, METR, PAMP, TGNO4, GD35, GD38, AMZN, GLD, GOOGL, NVDA, QQQ, XLU, … |
| Linter informe 7 secciones | PASS — attempt 1, 0 violations |
| Validator plan | PASS |
| MEP | implícito ≈ 1509.85 alineado con overlay statement; sin warning |
| Diagnóstico | Hiperconcentración energía AR (~31.5% YPFD+VIST); YPFD ~29.3% |
| Acción principal | Reducir YPFD qty=40 (desconcentrar); resto mayormente mantener |
| A2A | Degradado (`revisión externa no disponible`) — esperado si `make a2a` no corre |
| LangSmith | No configurado |

**Correcciones aplicadas en esta sesión (entrega):**

1. Parser `compact` vs `broker_wide` + ADR-0010 Proposed.
2. Cotizaciones: precios del snapshot pisan el feed para tickers de la cartera; MEP implícito si faltaban en market-data.
3. `tmp/` en `.gitignore`.
4. README reescrito (xlsx propio, imágenes, HITL, Anthropic/Google/Ollama).
5. Assert RAG F4: doc esperado en top-3 (embeddings no deterministas al #1).
6. Fixture sintética de layout bróker: `fixtures/estadocuenta-broker-layout.xlsx`.

**Limitaciones honestas para el PDF:**

- Sin imágenes propias de stops → técnico sin lecturas; gaps vía HITL si se piden niveles finos.
- `predict_trend` (ML) no cubre todos los tickers nuevos (artefacto entrenado sobre universo acotado).
- Con `MARKET_FIXTURE=1`, CCL/oficial siguen de fixture; quotes de cartera se alinean al estado.
- MCP live de panel existe en código pero la demo/entrega no depende de APIs vivas.
- Redactor a veces necesita fallback estructural (log `redactor_structure_fallback`) — el linter igual aprueba.

---

## Estructura sugerida del PDF

Basarse en `docs/INFORME-esqueleto.md` y enriquecer con E2E real:

1. Portada + resumen ejecutivo (1 página).
2. Introducción / problema / justificación multiagente.
3. Arquitectura + diagrama LangGraph + roster 1+5 vs deterministas.
4. Decisiones y trade-offs (tabla ADR 0001–0009 + **0010 Proposed**).
5. Seguridad / PII / guardrails 3 capas.
6. Evaluación (tabla de `evals/RESULTS.md`) + mención E2E cartera real (sin datos personales).
7. Limitaciones y trabajo futuro.
8. Apéndice: cómo correr (puntero al README), Agent Card A2A, estructura §6.3 del informe al usuario.

**Tono:** académico, rioplatense técnico, sin marketing. Enfatizar trade-offs explícitos (rúbrica).

**Prohibido en el PDF:** nombres reales, nros de comitente, montos exactos de la cuenta personal si el enunciado pide anonimizar — usar `INV-001`, porcentajes y tickers públicos.

---

## Guion de presentación oral (examen)

| Min | Bloque | Qué mostrar / decir |
|---|---|---|
| 0–1 | Problema | Revisión on-demand de cartera AR; no es chatbot con tools |
| 1–3 | Por qué multiagente | Modalidades distintas (tabular / web / visión); frontera ADR-0002 |
| 3–6 | Arquitectura | Diagrama; HITL `interrupt`; doble SQLite; MCP×2; RAG; A2A degradable |
| 6–9 | Demo viva | `make demo` o corrida `--xlsx` scrubbeada; mostrar linter OK + restricción |
| 9–11 | Eval | GATE-F7 PASS; asserts + judge |
| 11–13 | Trade-offs | Costo vs calidad por rol; A2A único degradable; Chroma no paralelo |
| 13–15 | Límites + Q&A | No asesora ni ejecuta; parser multi-layout; precios del estado |

Preguntas típicas a anticipar:

- ¿Por qué 5 agentes y no 9?
- ¿Dónde vive la fuente de verdad numérica?
- ¿Qué pasa si cae A2A / market API?
- ¿Cómo evitás injection (web / imagen)?
- ¿Por qué Ollama en el YAML?

---

## Checklist DoD F8 (para quien cierre el zip)

- [x] Parser + E2E xlsx real (linter OK)
- [x] README uso real / modelos
- [x] `tmp/` gitignored; sin PII en repo
- [ ] `make demo` ensayada punta a punta (verificar antes de zip)
- [ ] Commit de cierre F8 + push (solo si el humano lo pide)
- [ ] PDF generado desde este handoff + INFORME

---

## Skills sugeridas

El agente que continue debería invocar:

1. **handoff** (esta skill) — si compacta otra vez tras el PDF.
2. **create-rule** — solo si hay que dejar reglas nuevas post-ADR-0010 Accepted.
3. **code-review** o **review-bugbot** — revisión pre-zip del diff F8.
4. **canvas** — si se quiere un artefacto visual interactivo del informe (opcional).
5. Lectura obligatoria antes de redactar: `docs/INFORME-esqueleto.md`, `evals/RESULTS.md`, `docs/adrs/ADR-0010-parser-multi-layout.md`, `README.md`.

---

## Comandos útiles (referencia rápida)

```bash
make install
make test
make run XLSX=tmp/mi-estado.xlsx
make run MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml
make a2a   # otra terminal
make demo
make eval
```

---

## Nota de privacidad

Este handoff **no** incluye titular, comitente ni path con datos personales. El archivo real del bróker vive solo en `tmp/` local y no debe versionarse.
