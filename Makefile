PYTHON ?= python3.14
VENV ?= .venv

VENV_PYTHON := $(VENV)/bin/python
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy
PYTEST := $(VENV)/bin/pytest

.DEFAULT_GOAL := help

.PHONY: help commands bootstrap format format-check lint typecheck test docs-check inference-eval ranking-eval milestone-11-eval demo demo-synthetic briefing web web-open connector-status scheduled-readiness scheduled-dry-run scheduled-install scheduled-update-time scheduled-status scheduled-disable scheduled-enable scheduled-remove scheduled-notify-test check

help:
	@printf '%s\n' \
		'Chief of Staff commands' \
		'' \
		'Everyday use' \
		'  make web-open              Start the local interface and open it' \
		'  make web                   Start the local interface' \
		'  make briefing              Generate an on-demand live briefing' \
		'  make connector-status      Inspect connector health' \
		'  make scheduled-status      Inspect the scheduled trial' \
		'  make scheduled-disable     Pause scheduled generation' \
		'  make scheduled-enable      Resume scheduled generation' \
		'  make scheduled-notify-test Send a private-safe test notification' \
		'' \
		'Scheduled-trial setup' \
		'  make scheduled-readiness   Check host and connector readiness' \
		'  make scheduled-dry-run     Preview policy without retrieving data' \
		'  make scheduled-install     Install the approved LaunchAgent' \
		'  make scheduled-update-time Apply the accepted 6 a.m. trigger' \
		'  make scheduled-remove      Remove the LaunchAgent, preserving history' \
		'' \
		'Development and validation' \
		'  make bootstrap             Create or refresh the development environment' \
		'  make check                 Run the complete repository gate' \
		'  make test                  Run tests' \
		'  make format                Format source files' \
		'  make format-check          Check source formatting' \
		'  make lint                  Run lint checks' \
		'  make typecheck             Run strict type checking' \
		'  make docs-check            Validate Markdown links and anchors' \
		'  make inference-eval        Run the inference evaluation' \
		'  make ranking-eval          Run the ranking evaluation' \
		'  make milestone-11-eval     Run the Milestone 11 evaluation' \
		'  make demo                  Generate the connector demonstration' \
		'  make demo-synthetic        Generate a reduced synthetic demonstration' \
		'' \
		'Run make help, make commands, or bare make to display this list.'

commands: help

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

scheduled-update-time:
	$(VENV_PYTHON) -m chief_of_staff.scheduled_cli update-schedule --confirm-trigger-hour 6

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
