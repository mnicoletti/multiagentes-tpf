# PortfolioSentinel

Sistema multiagente para revisión on-demand de una cartera minorista argentina
(LangGraph + MCP + RAG + A2A consultivo). **No ejecuta órdenes**; todo informe
incluye descargo de no-asesoramiento.

Diseño: [`docs/SPEC-portfoliosentinel.md`](docs/SPEC-portfoliosentinel.md) ·
ADRs en [`docs/adrs/`](docs/adrs/) · informe académico en
[`docs/INFORME-esqueleto.md`](docs/INFORME-esqueleto.md).

## Requisitos

- Python 3.11+
- `make`
- Una clave de LLM **o** [Ollama](https://ollama.com) local

## Instalación

```bash
make install          # .venv + deps + fixtures (xlsx sintético, layout bróker, ML, imágenes)
# Creá .env con ANTHROPIC_API_KEY y/o GOOGLE_API_KEY (nunca lo commitees)
make lint
make test             # equivale a MARKET_FIXTURE=1 pytest
```

En `.env` (nunca lo commitees):

```bash
# Elegí según el YAML de modelos (ver sección Modelos)
ANTHROPIC_API_KEY=...
# GOOGLE_API_KEY=...
# LANGSMITH_API_KEY=...   # opcional, observabilidad
```

## Modelos (Anthropic / Google / Ollama)

Toda instanciación pasa por `init_chat_model` + YAML por rol (ADR-0009).
**No hay modelos hardcodeados en el grafo.**

| Proveedor | YAML | Variable de entorno | Cómo correr |
|---|---|---|---|
| Anthropic (default) | `src/portfoliosentinel/config/models.yaml` | `ANTHROPIC_API_KEY` | `make run` |
| Google Gemini | `src/portfoliosentinel/config/models.gemini.yaml` | `GOOGLE_API_KEY` | `MODELS_YAML=src/portfoliosentinel/config/models.gemini.yaml make run` |
| Ollama local | `src/portfoliosentinel/config/models.ollama.yaml` | (ninguna; daemon Ollama) | `MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml make run` |

También podés exportar `PORTFOLIOSENTINEL_MODELS_YAML=...` en lugar de `MODELS_YAML=`.

### Receta Ollama

```bash
ollama pull qwen3:8b          # orquestador / tool calling
ollama pull qwen2.5vl:7b      # visión (Analista Técnico)
make run MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml
```

El orquestador necesita un modelo con **tool calling** confiable (`qwen3` o similar).
El rol `tecnico` necesita visión multimodal; con solo-texto la lectura de gráficos degrada.

## Tu estado de cuenta (`.xlsx` propio)

El parser es **multi-layout** (ADR-0010): normaliza el export del bróker o la fixture
sintética a un `AccountSnapshot` tipado. Scrubbing de PII → alias `INV-001` antes de
cualquier LLM o BD.

```bash
# Copiá tu estado a un path local (tmp/ está en .gitignore)
cp ~/Descargas/estadocuenta.xlsx tmp/mi-estado.xlsx

make run XLSX=tmp/mi-estado.xlsx

# o CLI directa:
.venv/bin/python -m portfoliosentinel.cli run \
  --xlsx tmp/mi-estado.xlsx \
  --market-fixture \
  --confirm-constraints
```

### Carteras de ejemplo (`docs/ejemplos/`)

Hay cuatro estados **sintéticos y anonimizados** (layout bróker) listos para
probar sin datos personales. Perfiles y composición:
[`docs/ejemplos/README.md`](docs/ejemplos/README.md).

```bash
make run XLSX=docs/ejemplos/comitente-02-agresivo-energia.xlsx
```

Los **tickers nuevos** se reconocen solos desde el snapshot (sin lista humana ni HITL).

### Cotizaciones y MEP

| Modo | Cómo | Uso |
|---|---|---|
| Fixture de mercado | `--market-fixture` / `MARKET_FIXTURE=1` | Demo/evals sin red |
| Live (MCP market-data) | sin `--market-fixture` | dolarapi + panel (si hay red) |
| Precios del estado | automático | Si faltan tickers en el feed, se usan `PRECIO` del `.xlsx` y el MEP implícito del estado |

Para una cartera real con papeles fuera de la fixture, la valuación del día del
estado completa las cotizaciones faltantes. El diseño asume un MCP live; la
prueba local no depende de que el panel conozca cada ticker de antemano.

**Privacidad:** no commitees `.xlsx` reales ni imágenes con datos del titular.
Usá `tmp/` (gitignored) o `*.local.xlsx`.

## Informe en Markdown

Al terminar una corrida con linter OK, el informe se guarda como `.md` en
`output/reports/` (configurable con `--output-dir`). **No se vuelca el cuerpo
en consola**: solo se imprime el path absoluto, por ejemplo:

```text
Informe guardado: /…/output/reports/informe-<run_id>.md
```

Abrí ese archivo para leerlo. Recomendamos [Obsidian](https://obsidian.md/)
(app local para notas Markdown): sitio oficial [obsidian.md](https://obsidian.md/) ·
[descarga](https://obsidian.md/download). Podés abrir `output/reports` como vault
o arrastrar el `.md` a Obsidian.

`output/` está en `.gitignore`: no versiones informes de cuentas reales.

## Imágenes (análisis técnico / FCI)

Pasá paneles y gráficos con `--image path::purpose` (purpose declarado por vos):

```bash
.venv/bin/python -m portfoliosentinel.cli run \
  --xlsx tmp/mi-estado.xlsx \
  --market-fixture --confirm-constraints \
  --image fixtures/images/fci-panel.png::fci_panel \
  --image path/a/chart-ypfd.png::stop_chart \
  --image path/a/chart-screening.png::screening
```

Purposes útiles: `fci_panel`, `stop_chart`, `screening` (u otros que declares).
Si falta un stop/nivel fino, el grafo hace `interrupt()` (HITL) — **no inventa niveles**.

### Resume HITL (gaps / echo-back / escalate)

```bash
# Tras un interrupt (anotá el thread_id que imprime la CLI):
.venv/bin/python -m portfoliosentinel.cli resume --thread-id <id> \
  --image path/a/chart-ypfd.png::stop_chart \
  --stop-level YPFD=45000

# Echo-back de restricciones (si no usaste --confirm-constraints):
.venv/bin/python -m portfoliosentinel.cli resume --thread-id <id>
```

Inspección del checkpoint:

```bash
make inspect THREAD_ID=<id>
```

## Ejemplos de uso

```bash
# 1. Corrida feliz (fixture sintética, default --xlsx)
make run

# 2. Cartera de ejemplo (docs/ejemplos/; ver perfiles allí)
make run XLSX=docs/ejemplos/comitente-02-agresivo-energia.xlsx

# 3. Estado de cuenta propio (detalle en sección anterior)
make run XLSX=tmp/mi-estado.xlsx

# 4. Restricción + capital nuevo
.venv/bin/python -m portfoliosentinel.cli run --market-fixture --confirm-constraints \
  --constraint "no vender YPFD" --capital-new 500000

# 5. Resume HITL tras interrupt (anotá el thread_id que imprime la CLI)
.venv/bin/python -m portfoliosentinel.cli resume --thread-id <id> \
  --stop-level YPFD=45000

# Modo degradado (sin .xlsx; último snapshot del store)
.venv/bin/python -m portfoliosentinel.cli run --no-xlsx --confirm-constraints --market-fixture

# Solo grafo determinista (stubs LLM; sin gastar tokens)
.venv/bin/python -m portfoliosentinel.cli run --skip-llm --confirm-constraints --market-fixture
```

## A2A (compliance consultivo)

Proceso separado (ADR-0008). Si está caído, el grafo **sigue** y el informe marca
`revisión externa no disponible`.

```bash
# Terminal 1
make a2a
# Terminal 2
curl -s http://127.0.0.1:8765/.well-known/agent.json | head
make run
```

Agent Card: `GET /.well-known/agent.json` — skill `review_plan`.
JSON-RPC: `POST /a2a` con `message/send`.
Demo sin LLM en el revisor: `A2A_SKIP_LLM=1 make a2a`.

## Demo F8 / Eval

```bash
make demo   # guion: feliz → restricción → gap/resume → eval parser → BD append-only
make eval   # golden cases + escenarios
```

Judge Gemini (opcional):

```bash
PORTFOLIOSENTINEL_JUDGE_MODELS_YAML=evals/judge/models.gemini.yaml \
PORTFOLIOSENTINEL_MODELS_YAML=src/portfoliosentinel/config/models.gemini.yaml \
  make eval
```

Resultados: [`evals/RESULTS.md`](evals/RESULTS.md).

## Variables de entorno

| Variable | Rol |
|---|---|
| `PORTFOLIOSENTINEL_MODELS_YAML` | Override de modelos por rol |
| `MARKET_FIXTURE=1` | FX/quotes/web desde `fixtures/` |
| `A2A_BASE_URL` | Base del compliance (default `http://127.0.0.1:8765`) |
| `A2A_SKIP_LLM=1` | Revisor A2A solo con reglas deterministas |
| `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` | Proveedor LLM |
| `LANGSMITH_API_KEY` | Trazas opcionales |

## Arquitectura (una línea)

Orquestador + 5 especialistas (Cartera, Mercado, Técnico, Planificador, Redactor)
+ parser/calculadora/validator/linter/ML deterministas + 2 MCP (`portfolio-store`,
`market-data`) + Chroma + A2A consultivo. Checkpointer SQLite ≠ store de dominio
append-only (ADR-0003).

## Make targets

| Target | Qué hace |
|---|---|
| `make install` | venv + deps + fixtures |
| `make run` | corrida `MARKET_FIXTURE=1` + `--confirm-constraints` |
| `make run XLSX=tmp/mi.xlsx` | misma corrida con tu estado |
| `make run XLSX=docs/ejemplos/comitente-0N-….xlsx` | corrida con cartera de ejemplo |
| `make run MODELS_YAML=...` | override de modelos |
| `make a2a` | compliance en `:8765` |
| `make demo` | guion F8 |
| `make eval` | GC + escenarios |
| `make test` | pytest con fixture de mercado |
| `make lint` | ruff |
| `make inspect THREAD_ID=…` | checkpoint |
| `make ingest-knowledge` | reingesta corpus RAG |
