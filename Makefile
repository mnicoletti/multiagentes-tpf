.PHONY: lint run eval demo install test inspect ingest-knowledge

# Preferí el venv local si existe (PEP 668 / Homebrew).
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# Override opcional: PORTFOLIOSENTINEL_MODELS_YAML=... make run
MODELS_YAML ?=

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/python scripts/build_synthetic_fixture.py
	.venv/bin/python scripts/train_trend_model.py
	.venv/bin/python scripts/build_image_fixtures.py

lint:
	$(PYTHON) -m ruff check src tests scripts mcp_servers
	$(PYTHON) -m ruff format --check src tests scripts mcp_servers

run:
	@if [ -n "$(MODELS_YAML)" ]; then \
		PORTFOLIOSENTINEL_MODELS_YAML="$(MODELS_YAML)" MARKET_FIXTURE=1 $(PYTHON) -m portfoliosentinel.cli run --market-fixture; \
	else \
		MARKET_FIXTURE=1 $(PYTHON) -m portfoliosentinel.cli run --market-fixture; \
	fi

inspect:
	@test -n "$(THREAD_ID)" || (echo "Uso: make inspect THREAD_ID=<id>"; exit 1)
	$(PYTHON) -m portfoliosentinel.cli inspect --thread-id "$(THREAD_ID)"

ingest-knowledge:
	MARKET_FIXTURE=1 $(PYTHON) -c "from portfoliosentinel.rag.ingest import ingest_knowledge; print(ingest_knowledge())"

eval:
	@echo "make eval: stub — el harness de evals se implementa en F7"
	@exit 1

demo:
	@echo "make demo: stub — la demo end-to-end se completa en F8"
	@exit 1

test:
	MARKET_FIXTURE=1 $(PYTHON) -m pytest tests -q
