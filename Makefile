.PHONY: lint run eval demo install test inspect

# Preferí el venv local si existe (PEP 668 / Homebrew).
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

# Override opcional: PORTFOLIOSENTINEL_MODELS_YAML=... make run
MODELS_YAML ?=

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/python scripts/build_synthetic_fixture.py

lint:
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts

run:
	@if [ -n "$(MODELS_YAML)" ]; then \
		PORTFOLIOSENTINEL_MODELS_YAML="$(MODELS_YAML)" $(PYTHON) -m portfoliosentinel.cli run; \
	else \
		$(PYTHON) -m portfoliosentinel.cli run; \
	fi

inspect:
	@test -n "$(THREAD_ID)" || (echo "Uso: make inspect THREAD_ID=<id>"; exit 1)
	$(PYTHON) -m portfoliosentinel.cli inspect --thread-id "$(THREAD_ID)"

eval:
	@echo "make eval: stub — el harness de evals se implementa en F7"
	@exit 1

demo:
	@echo "make demo: stub — la demo end-to-end se completa en F8"
	@exit 1

test:
	$(PYTHON) -m pytest tests -q
