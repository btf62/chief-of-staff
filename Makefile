PYTHON ?= python3.14
VENV ?= .venv

VENV_PYTHON := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest

.PHONY: bootstrap format format-check lint typecheck test docs-check demo demo-synthetic briefing check

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade "pip>=25.1"
	$(VENV_PYTHON) -m pip install --editable . --group dev

format:
	$(RUFF) format .
	$(RUFF) check --fix .

format-check:
	$(RUFF) format --check .

lint: format-check
	$(RUFF) check .

typecheck:
	$(MYPY) src tests tools examples

test:
	$(PYTEST)

docs-check:
	$(VENV_PYTHON) tools/validate_markdown.py

demo:
	$(VENV_PYTHON) examples/generate_connector_briefing.py

demo-synthetic:
	$(VENV_PYTHON) examples/generate_reduced_briefing.py

briefing:
	$(VENV_PYTHON) -m chief_of_staff.gmail_live_cli briefing

check: lint typecheck test docs-check
