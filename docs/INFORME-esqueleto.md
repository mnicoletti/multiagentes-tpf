# PortfolioSentinel — Informe del TPO (esqueleto)

> Informe requerido por la Opción A del enunciado (arquitectura, decisiones y trade-offs, limitaciones, trabajo futuro), ampliado con evaluación, seguridad y observabilidad porque son ejes declarados de las preguntas del final. Los bloques `> [!TODO]` se completan durante/después de la implementación con datos observados — todo lo demás ya está redactado y solo requiere revisión final. Fuente de las decisiones: [[SPEC-portfoliosentinel]] y ADRs 0001–0009.

## 1. Introducción

**Problema.** Un inversor minorista argentino realiza periódicamente, a demanda, una revisión integral de su cartera (acciones MERVAL, CEDEARs, bonos hard-dollar, un FCI externo al estado de cuenta): diagnóstico de concentraciones, acción concreta por instrumento, screening de candidatos nuevos y asignación de capital adicional. La tarea combina fuentes heterogéneas (un `.xlsx` de bróker, imágenes de paneles y gráficos técnicos, texto libre con restricciones y capital), contexto de mercado en tiempo real y restricciones personales inviolables. Hecha a mano insume horas de analista y es propensa a inconsistencias numéricas.

**Justificación multiagente.** No es un chatbot con tools: cada especialista opera sobre una *modalidad de entrada distinta* (tabular tipado, web con citas, visión sobre gráficos), con *herramientas distintas* y *criterios de expertise distintos*, coordinados por un supervisor con estado compartido, puntos de interrupción humana y un ciclo de validación-replanificación que corta el grafo entre diagnóstico y plan. La descomposición responde a un criterio único y auditable: **es agente solo lo que requiere juicio de LLM; todo lo verificable es código determinista** (ADR-0002). El sistema no ejecuta órdenes y todo informe incluye descargo de no-asesoramiento.

**Objetivos funcionales:** informe por instrumento con acción y cantidades; radiografía con clustering semántico por driver de riesgo; integración de un activo externo (FCI) vía visión; screening técnico de no-poseídos; plan de rebalanceo con capital nuevo; comparación contra el último snapshot; solicitud explícita de inputs faltantes en lugar de inventar niveles.
**Objetivos no funcionales:** fidelidad numérica absoluta al estado de cuenta; trazabilidad de cada recomendación; reproducibilidad de la demo sin APIs vivas; intercambiabilidad de proveedor de LLM (incl. modelos locales); costo por corrida medido.

## 2. Arquitectura general

Orquestador-supervisor (LangGraph) + 5 agentes especialistas (Cartera, Mercado, Técnico-visión, Planificador, Redactor) + 4 componentes deterministas (parser `.xlsx`, calculadora de rebalanceo, validator/linter de guardrails, tool ML). Estado compartido `PortfolioState` con checkpointer SQLite (sesiones, `interrupt()`/resume). Persistencia de dominio append-only (snapshots, restricciones, informes) vía server MCP propio; datos de mercado vía segundo server MCP con modo fixture; web search nativa; RAG híbrido (corpus metodológico estático + informes propios) sobre Chroma embebido; revisión externa consultiva vía protocolo A2A (servicio FastAPI con Agent Card).

> [!TODO] Insertar diagrama final (Excalidraw/Mermaid) y el flujo numerado de SPEC §4.3 ajustado a lo efectivamente construido.

## 3. Decisiones de diseño y trade-offs

Cada decisión tiene ADR con opciones consideradas y consecuencias; acá el resumen y su trade-off central:

| Decisión | Trade-off asumido | ADR |
|---|---|---|
| LangGraph puro (no ADK ni mezcla) | Madurez HITL/checkpointing vs implementar A2A a mano | 0001 |
| Frontera agente/determinista, roster 1+5 | Un hop más de latencia por separar diagnóstico/plan, a cambio de un punto de corte para el validator y números testeables | 0002 |
| Doble persistencia; dominio append-only; modo degradado sin `.xlsx` | Dos almacenes que correlacionar vs trazabilidad total y delta histórico | 0003 |
| RAG híbrido con Chroma embebido | Costo de escribir el corpus vs RAG demostrable desde la corrida uno y conocimiento fuera de los prompts | 0004 |
| Dos MCP custom + web search nativa + modo fixture | Mantener dos servers vs demostrar construcción de MCP y demo inmune a APIs caídas | 0005 |
| Guardrails 3 capas, deterministas en los bordes | Formato de salida más rígido para el Redactor vs restricciones y coherencia numérica verificadas por código | 0006 |
| Evaluación híbrida (asserts + judge acotado) | Fixtures que mantener vs reproducibilidad y explicabilidad | 0007 |
| A2A consultivo no bloqueante (único ítem degradable) | Rol simulado vs protocolo real sin riesgo para la demo | 0008 |
| Modelos por rol (Sonnet juicio/visión, Haiku ruteo/síntesis), YAML + Ollama | Matriz de combinaciones vs costo optimizado, reversible y sin lock-in | 0009 |

Trade-offs transversales del enunciado, resueltos: **costo vs calidad** → por rol, medido (ADR-0009); **autonomía vs control humano** → autonomía dentro de la corrida, humano en restricciones, gaps y confirmaciones (`interrupt()`); **rapidez vs precisión** → precisión primero (el sistema prefiere pausar y pedir un gráfico antes que inventar un stop); **memoria persistente vs costo** → append-only en SQLite local, costo despreciable, valor de auditoría alto.

## 4. Seguridad

Tres capas (ADR-0006): validación estructural y scrubbing de PII en el borde de entrada (el LLM nunca ve titular/comitente ni un `.xlsx` malformado); separación instrucción/dato en prompts con dos vectores de injection identificados (resultados web, texto incrustado en imágenes); linter determinista de salida con templates YAML (restricciones duras, cantidades ≤ tenencia, descargo, sin lenguaje de ejecución, estructura). Datos reales fuera del repo; fixture sintética como único dato versionado. Autenticación/autorización multiusuario: fuera de scope por ser sistema single-user local — ver Trabajo futuro.

> [!TODO] Pegar 1 ejemplo real de rechazo del linter y 1 traza del escenario de injection (E-3).

## 5. Evaluación y resultados

Diseño en ADR-0007: GC-1 (corrida feliz, asserts deterministas + judge), GC-2 (tentación de violar la restricción — testea el loop Planificador↔Validator), escenarios E-1..E-4 (degradado, gap→interrupt, injection, xlsx malformado), judge Sonnet t=0 con rúbrica 1–5 (faithfulness, relevancy, completitud). Criterios de aceptación: deterministas 100%, judge ≥ 4/5, costo/corrida < umbral.

> [!TODO] Volcar `evals/RESULTS.md`: tabla de resultados por caso, scores del judge por dimensión, latencia y costo promedio por corrida, tasa de re-ruteos del validator, y una lectura de 3–4 líneas por hallazgo.

## 6. Observabilidad

LangSmith (tracing entre agentes, tokens, costo) correlacionado por `run_id`/`thread_id` con los registros append-only de la BD de dominio: auditoría punta a punta de cada recomendación hasta su dato de origen. Logs estructurados en nodos deterministas.

> [!TODO] Screenshot de una traza completa (fan-out analítico + rechazo del validator + resume post-interrupt).

## 7. Limitaciones

Pre-identificadas en diseño (completar con lo observado):
- Calidad de la lectura técnica de gráficos depende del modelo de visión; con modelos locales (Ollama multimodal) degrada sensiblemente (ADR-0009).
- El clustering semántico es juicio de LLM: puede clasificar mal un driver ante instrumentos atípicos; mitigado por el corpus de criterios (RAG) pero no eliminado.
- Chroma embebido y SQLite no escalan multiusuario/concurrente — correcto para el scope, insuficiente como producto.
- El agente A2A es un rol simulado: protocolo real, contraparte ficticia.
- Dependencia de tool calling del proveedor para el orquestador con modelos locales.
- Latencia total de una corrida completa: [!TODO medir] — el diseño prioriza precisión y auditabilidad sobre velocidad.

> [!TODO] Agregar 2–3 limitaciones *encontradas* durante la implementación (las más honestas rinden más en la defensa que las genéricas).

## 8. Trabajo futuro

Comparación automática multi-snapshot (tendencias de la cartera en el tiempo, no solo delta contra el último); Reflection en el Planificador (autocrítica previa al validator para bajar re-ruteos); Self-Correcting RAG sobre el corpus metodológico; autenticación y multiusuario si el sistema saliera del ámbito personal; segundo agente A2A real (integración con un proveedor de datos que exponga el protocolo); ejecución opcional de órdenes con doble confirmación humana — hoy excluida por diseño y por prudencia regulatoria.

## 9. Conclusiones

> [!TODO] Redactar al final (5–10 líneas): qué demostró el sistema respecto de los conceptos de la materia (coordinación, state, HITL, MCP, RAG, evaluación, guardrails, A2A), qué haría distinto, y una frase honesta sobre el límite entre lo que el multiagente aporta y lo que sigue siendo criterio humano del inversor.

---

## Anexo A — Preguntas de final anticipadas (chuleta de dos frases)

- **¿Por qué multiagente y no un chatbot con tools?** Modalidades, herramientas y expertise distintos por especialista, coordinados con estado compartido y un ciclo validación-replanificación; un monolito no puede cortar el grafo entre diagnóstico y plan ni pausar para pedir inputs.
- **¿Por qué el parser no es un agente?** Porque los números son la fuente de verdad y un LLM puede alucinarlos; todo lo verificable es código.
- **¿Por qué un judge distinto/configurado aparte?** Para que el sistema no se corrija a sí mismo con sus propios sesgos.
- **¿Por qué golden cases con fixtures?** Reproducibilidad: misma corrida, mismo resultado, con la API de mercado grabada.
- **¿Por qué el A2A no bloquea?** Es un tercero consultivo; las restricciones del usuario las aplica el validator interno.
- **¿Y si Haiku no alcanza en Mercado?** La config es por rol en YAML: se sube el modelo y se re-corre el eval; decisión reversible e instrumentada.
- **¿Qué pasa sin `.xlsx`?** Modo degradado explícito sobre el último snapshot, con staleness marcado y cantidades finas condicionadas.
- **¿Qué pasa si falta un gráfico para un stop?** `interrupt()`: el sistema pide el input y reanuda la misma sesión; nunca inventa niveles.
