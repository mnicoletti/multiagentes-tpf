# PortfolioSentinel

Sistema multiagente para revisión on-demand de una cartera minorista argentina.

## Setup

```bash
make install          # crea .venv, instala deps y regenera la fixture sintética
make lint
make test             # parser + grafo + store F3 (sin LLM)
```

## Corrida (F3)

```bash
# Default: models.yaml (Anthropic). Requiere ANTHROPIC_API_KEY.
# --confirm-constraints evita el interrupt HITL del echo-back.
.venv/bin/python -m portfoliosentinel.cli run --confirm-constraints

# Local con Ollama (sin API paga):
make run MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml

# Modo degradado (sin .xlsx; usa último snapshot del store de dominio):
.venv/bin/python -m portfoliosentinel.cli run --no-xlsx --confirm-constraints
```

Inspección de checkpoint por `thread_id`:

```bash
.venv/bin/python -m portfoliosentinel.cli run --stop-after intake --thread-id demo-f3 --confirm-constraints
make inspect THREAD_ID=demo-f3
.venv/bin/python -m portfoliosentinel.cli resume --thread-id demo-f3
```

MCP store de dominio (stdio):

```bash
.venv/bin/python -m mcp_servers.portfolio_store
```

## Notas

- Cero PII real en el repo: solo la fixture `fixtures/estadocuenta-sintetico.xlsx` (alias post-parse `INV-001`).
- Modelos por rol en `src/portfoliosentinel/config/models.yaml` vía `init_chat_model` (ADR-0009).
- Override de YAML: env `PORTFOLIOSENTINEL_MODELS_YAML`.
- Checkpointer SQLite: `data/checkpoints.sqlite` (ejecución). Store de dominio: `data/portfolio_store.sqlite` (append-only). Son dos BD distintas (ADR-0003).
- `make eval` / `make demo` siguen stubs hasta F7/F8.
