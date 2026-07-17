# ADR-0009: Asignación de modelos por rol con abstracción de proveedor

**Status:** Accepted · **Date:** 2026-07-15 · **Deciders:** Max (confirmado en grill, con requisito adicional: intercambiable a modelos locales vía Ollama)

## Context
El enunciado lista "elección de modelos" como decisión a justificar y "dependencia del proveedor" como limitación típica. La demo usa créditos de Anthropic; el profesor debe poder usar los suyos; el autor exige poder correr con Ollama.

## Decision Drivers
- Trade-off costo/calidad resuelto **por rol** y medible (LangSmith reporta costo/corrida).
- Reversibilidad: subir/bajar un modelo = editar YAML, cero código.
- Mitigar vendor lock-in por diseño.

## Options Considered
**A. Un solo modelo top para todo** — simple pero caro; desperdicia el ítem de trade-off de la rúbrica.
**B. Un solo modelo barato para todo** — degrada visión y planificación, los roles donde no hay opción económica confiable.
**C. Dos niveles por rol, configurados en YAML** — elegida.

## Decision
- **Sonnet (juicio/visión):** Analista de Cartera, Analista Técnico (multimodal), Planificador, Redactor.
- **Haiku (estructurado/frecuente):** Orquestador (ruteo), Analista de Mercado (escalable a Sonnet si los evals de faithfulness lo piden — el harness da el dato), agente A2A.
- **Judge:** Sonnet t=0, configuración independiente y versionada.
- **Abstracción:** `init_chat_model` de LangChain; `config/models.yaml` con `provider` + `model` + params por rol. **Ollama es un provider más** (`langchain-ollama`).
- **Limitaciones conocidas con modelos locales (documentar, no resolver):** el Analista Técnico requiere modelo con visión (llama3.2-vision, qwen2.5-vl) con calidad de lectura de gráficos sensiblemente menor; el orquestador depende de tool calling, variable entre modelos locales — elegir uno que lo soporte.

## Consequences
- (+) Costo por corrida optimizado y medido; decisión reversible e instrumentada.
- (+) Argumento de defensa: "puedo correr el sistema entero sin ninguna API paga".
- (−) Matriz de pruebas crece por combinación de modelos — acotado: los evals corren sobre la config de demo; otras configs son best-effort documentado.

**Trazabilidad rúbrica:** "elección de modelos" (§9); trade-off costo vs calidad (§10); limitación "dependencia del proveedor" mitigada (§11).
