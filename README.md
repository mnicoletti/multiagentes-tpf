# PortfolioSentinel

Sistema multiagente para revisión on-demand de una cartera minorista argentina.

## Setup (F1)

```bash
make install          # crea .venv, instala deps y regenera la fixture sintética
make lint
make test             # pytest tests/parser
```

## Notas

- Cero PII real en el repo: solo la fixture `fixtures/estadocuenta-sintetico.xlsx` (alias post-parse `INV-001`).
- Modelos por rol en `src/portfoliosentinel/config/models.yaml` vía `init_chat_model` (ADR-0009).
- `make run` / `make eval` / `make demo` son stubs hasta fases posteriores.
