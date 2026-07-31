PYTHON ?= python3.14
VENV ?= .venv

VENV_PYTHON := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest

.PHONY: bootstrap format format-check lint typecheck test docs-check inference-eval ranking-eval milestone-11-eval demo demo-synthetic briefing web web-open connector-status scheduled-readiness scheduled-dry-run scheduled-install scheduled-status scheduled-disable scheduled-enable scheduled-remove scheduled-notify-test check

bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade "pip>=25.1"
	$(VENV_PYTHON) -m pip install --upgrade --force-reinstall --editable . --group dev

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

inference-eval:
	$(VENV_PYTHON) tools/evaluate_inference.py

ranking-eval:
	$(VENV_PYTHON) tools/evaluate_ranking.py

milestone-11-eval:
	$(VENV_PYTHON) tools/evaluate_milestone_11.py

demo:
	$(VENV_PYTHON) examples/generate_connector_briefing.py

demo-synthetic:
	$(VENV_PYTHON) examples/generate_reduced_briefing.py

briefing:
	$(VENV_PYTHON) -m chief_of_staff.gmail_live_cli briefing

web:
	$(VENV_PYTHON) -m chief_of_staff.web.server

web-open:
	$(VENV_PYTHON) -m chief_of_staff.web.server --open

connector-status:
	$(VENV_PYTHON) -m chief_of_staff.operations_cli connector-status

scheduled-readiness:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli readiness

scheduled-dry-run:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli dry-run

scheduled-install:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli install --confirm-primary-host

scheduled-status:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli status

scheduled-disable:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli disable

scheduled-enable:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli enable

scheduled-remove:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli remove

scheduled-notify-test:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli notify-test

check: lint typecheck test docs-check inference-eval ranking-eval
