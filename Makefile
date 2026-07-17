.PHONY: lint run eval demo install test

# Preferí el venv local si existe (PEP 668 / Homebrew).
PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)

install:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/python scripts/build_synthetic_fixture.py

lint:
	$(PYTHON) -m ruff check src tests scripts
	$(PYTHON) -m ruff format --check src tests scripts

# Stubs de fases posteriores — F1 solo implementa lint de verdad.
run:
	@echo "make run: stub F1 — el grafo se implementa en F2+"
	@exit 1

eval:
	@echo "make eval: stub F1 — el harness de evals se implementa en F7"
	@exit 1

demo:
	@echo "make demo: stub F1 — la demo end-to-end se completa en F8"
	@exit 1

test:
	$(PYTHON) -m pytest tests/parser -q
