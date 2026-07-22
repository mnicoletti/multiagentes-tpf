.PHONY: lint run eval demo install test inspect ingest-knowledge a2a

# Preferí el venv local si existe (PEP 668 / Homebrew).
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# Override opcional: MODELS_YAML=... XLSX=... make run
MODELS_YAML ?=
XLSX ?=
A2A_HOST ?= 127.0.0.1
A2A_PORT ?= 8765

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/python scripts/build_synthetic_fixture.py
	.venv/bin/python scripts/build_broker_layout_fixture.py
	.venv/bin/python scripts/train_trend_model.py
	.venv/bin/python scripts/build_image_fixtures.py

lint:
	$(PYTHON) -m ruff check src tests scripts mcp_servers evals a2a_compliance
	$(PYTHON) -m ruff format --check src tests scripts mcp_servers evals a2a_compliance

run:
	@ARGS="--market-fixture --confirm-constraints"; \
	if [ -n "$(XLSX)" ]; then ARGS="$$ARGS --xlsx $(XLSX)"; fi; \
	if [ -n "$(MODELS_YAML)" ]; then \
		PORTFOLIOSENTINEL_MODELS_YAML="$(MODELS_YAML)" MARKET_FIXTURE=1 $(PYTHON) -m portfoliosentinel.cli run $$ARGS; \
	else \
		MARKET_FIXTURE=1 $(PYTHON) -m portfoliosentinel.cli run $$ARGS; \
	fi

inspect:
	@test -n "$(THREAD_ID)" || (echo "Uso: make inspect THREAD_ID=<id>"; exit 1)
	$(PYTHON) -m portfoliosentinel.cli inspect --thread-id "$(THREAD_ID)"

ingest-knowledge:
	MARKET_FIXTURE=1 $(PYTHON) -c "from portfoliosentinel.rag.ingest import ingest_knowledge; print(ingest_knowledge())"

eval:
	MARKET_FIXTURE=1 $(PYTHON) scripts/run_evals.py

a2a:
	A2A_HOST=$(A2A_HOST) A2A_PORT=$(A2A_PORT) A2A_SKIP_LLM=$${A2A_SKIP_LLM:-0} \
		$(PYTHON) -m a2a_compliance

demo:
	MARKET_FIXTURE=1 $(PYTHON) scripts/demo_f8.py

test:
	MARKET_FIXTURE=1 $(PYTHON) -m pytest tests -q
