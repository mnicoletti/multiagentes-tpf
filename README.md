# PortfolioSentinel

Sistema multiagente para revisión on-demand de una cartera minorista argentina.

## Setup

```bash
make install          # crea .venv, instala deps y regenera la fixture sintética
make lint
make test             # parser + grafo F2 (sin LLM)
```

## Corrida F2 (radiografía)

```bash
# Default: models.yaml (Anthropic). Requiere ANTHROPIC_API_KEY.
make run

# Local con Ollama (sin API paga):
make run MODELS_YAML=src/portfoliosentinel/config/models.ollama.yaml
```

Inspección de checkpoint por `thread_id`:

```bash
.venv/bin/python -m portfoliosentinel.cli run --stop-after orquestador --thread-id demo-f2
make inspect THREAD_ID=demo-f2
.venv/bin/python -m portfoliosentinel.cli resume --thread-id demo-f2
```

## Notas

- Cero PII real en el repo: solo la fixture `fixtures/estadocuenta-sintetico.xlsx` (alias post-parse `INV-001`).
- Modelos por rol en `src/portfoliosentinel/config/models.yaml` vía `init_chat_model` (ADR-0009).
- Override de YAML: env `PORTFOLIOSENTINEL_MODELS_YAML`.
- Checkpointer SQLite en `data/checkpoints.sqlite` (gitignored).
- `make eval` / `make demo` siguen stubs hasta F7/F8.
