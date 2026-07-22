# PortfolioSentinel

Sistema multiagente para revisión on-demand de una cartera minorista argentina
(LangGraph + MCP + RAG + A2A consultivo). No ejecuta órdenes; todo informe
incluye descargo de no-asesoramiento.

Diseño: `docs/SPEC-portfoliosentinel.md` · ADRs en `docs/adrs/` · informe académico
en `docs/INFORME-esqueleto.md`.

## Instalación

Requisitos: Python 3.11+, `make`, y una clave de LLM **o** Ollama local.

```bash
make install          # .venv + deps + fixture sintética + artefacto ML + imágenes
# Exportá ANTHROPIC_API_KEY / GOOGLE_API_KEY según el YAML de modelos
make lint
make test             # parser, grafo, store, A2A (sin red salvo lo que el test monte)
```

Variables útiles:

| Variable | Rol |
|---|---|
| `PORTFOLIOSENTINEL_MODELS_YAML` | Override de modelos por rol (ADR-0009) |
| `MARKET_FIXTURE=1` | FX/quotes/web desde `fixtures/` (demo sin APIs vivas) |
| `A2A_BASE_URL` | Base del servicio compliance (default `http://127.0.0.1:8765`) |
| `A2A_SKIP_LLM=1` | Revisor A2A solo con reglas deterministas |

## Ejecución

```bash
# Corrida completa (fixtures de mercado). Anthropic por defecto.
make run
# equivalente:
.venv/bin/python -m portfoliosentinel.cli run --market-fixture --confirm-constraints

# Con restricción + capital:
.venv/bin/python -m portfoliosentinel.cli run --market-fixture --confirm-constraints \
  --constraint "no vender YPFD" --capital-new 500000

# Modo degradado (sin .xlsx; último snapshot del store):
.venv/bin/python -m portfoliosentinel.cli run --no-xlsx --confirm-constraints --market-fixture

# Determinista (stubs LLM; útil para ensayar el grafo):
.venv/bin/python -m portfoliosentinel.cli run --skip-llm --confirm-constraints --market-fixture
```

### A2A (compliance consultivo)

Proceso separado (ADR-0008). Si está caído, el grafo **sigue** y el informe marca
`revisión externa no disponible`.

```bash
# Terminal 1
make a2a
# Terminal 2
curl -s http://127.0.0.1:8765/.well-known/agent.json | head
make run   # o make demo
```

Agent Card: `GET /.well-known/agent.json` — única skill `review_plan`.
JSON-RPC: `POST /a2a` con `message/send` (también acepta `tasks/send`).

### Demo ensayada (DoD F8)

```bash
make demo
```

Guion: corrida feliz → restricción YPFD → gap/resume → eval parser → BD append-only.

### Eval

```bash
make eval
# Judge Gemini (profesor):
PORTFOLIOSENTINEL_JUDGE_MODELS_YAML=evals/judge/models.gemini.yaml \
PORTFOLIOSENTINEL_MODELS_YAML=src/portfoliosentinel/config/models.gemini.yaml \
  make eval
```

Resultados: `evals/RESULTS.md`.

### Inspección / HITL

```bash
.venv/bin/python -m portfoliosentinel.cli run --stop-after intake \
  --thread-id demo-hitl --confirm-constraints --market-fixture
make inspect THREAD_ID=demo-hitl
.venv/bin/python -m portfoliosentinel.cli resume --thread-id demo-hitl
```

## Receta Ollama (sin API paga)

1. Instalá [Ollama](https://ollama.com) y bajá modelos:

```bash
# Orquestador / roles con tool calling (imprescindible):
ollama pull qwen3:8b
# Visión del Analista Técnico (lectura de paneles/gráficos):
ollama pull qwen2.5vl:7b
# Alternativa visión: llama3.2-vision
```

2. Apuntá el YAML local:

```bash
make run MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml
```

3. **Por qué el orquestador necesita tool calling.** El orquestador rutea y confirma
restricciones con herramientas estructuradas del grafo. Un modelo local sin tool
calling confiable falla el echo-back / ruteo. `qwen3` (o similar con tools) es el
mínimo razonable; no uses un modelo “chat-only” en ese rol.

4. **Visión.** En `models.ollama.yaml` el rol `tecnico` debe usar un modelo
multimodal (`qwen2.5vl`, `llama3.2-vision`, etc.). Con modelos solo-texto la
lectura de gráficos degrada o falla; es una limitación documentada (ADR-0009),
no un bug del grafo.

5. **A2A local.** El rol `a2a` también lee el YAML; para demo sin LLM en el
revisor: `A2A_SKIP_LLM=1 make a2a`.

## Arquitectura (una línea)

Orquestador + 5 especialistas (Cartera, Mercado, Técnico, Planificador, Redactor)
+ parser/calculadora/validator/linter/ML deterministas + 2 MCP (`portfolio-store`,
`market-data`) + Chroma + A2A consultivo. Checkpointer SQLite ≠ store de dominio
append-only (ADR-0003).

## Privacidad

Cero PII real en el repo. Única fixture: `fixtures/estadocuenta-sintetico.xlsx`
(alias post-parse `INV-001`). No commitear `.xlsx` ni imágenes reales del titular.

## Make targets

| Target | Qué hace |
|---|---|
| `make install` | venv + deps + fixtures |
| `make run` | corrida con `MARKET_FIXTURE=1` |
| `make a2a` | levanta compliance en `:8765` |
| `make demo` | guion F8 de 5 pasos |
| `make eval` | GC + escenarios |
| `make test` | pytest |
| `make lint` | ruff |
| `make inspect THREAD_ID=…` | checkpoint |
