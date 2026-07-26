# Changelog

All notable changes to this project will be documented here. The format is
inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

No strict versioning scheme is promised before a distributable product exists.

## [Unreleased]

### Added

- Initial documentation-first repository structure.
- Canonical locations for foundational, product, architecture, connector,
  decision, operations, and runbook documentation.
- Placeholder documents for the constitution, leadership model, future ideas,
  and Daily Briefing v1.
- Contribution and agent guidance.
- Accepted Version 1 Product Requirements, Daily Briefing v1 specification,
  and Architecture Overview.
- Focused implementation roadmap from the completed design baseline through
  on-demand product acceptance, with scheduled morning generation deferred.
- Python 3.14 package foundation using a `src` layout, standard-library virtual
  environment, and pip dependency groups.
- Exact-pinned Ruff, mypy, and pytest development tooling with shared Make
  targets and continuous integration.
- Validated non-secret configuration and deny-by-default structured logging
  boundaries with synthetic tests.
- Application-owned domain models and checksummed SQLite migrations for run
  metadata, provenance, conclusions, and append-oriented dispositions.
- Inspectable correction history, evidence-fingerprint recurrence projection,
  bounded run pruning, individual deletion, and complete local-state reset.
- Retrieval-only connector contracts, explicit invocation context,
  normalization, conservative exact deduplication, and source-coverage
  reporting.
- Structured deterministic briefing composition with canonical ordering,
  provenance, transparent priority inputs, duplicate controls, and enforced
  presentation budgets.
- A repository-owned synthetic briefing demonstration and full pipeline test
  coverage.
- An accepted exact-path repository-context connector with bounded Markdown
  extraction, relative provenance, and no source-content cache.
- A mock-only Google Calendar connector contract with exact read-only scope
  enforcement, pagination, all-day normalization, partial-failure retention,
  and distinct unauthorized and empty coverage.
- A safe on-demand connector demonstration combining repository-owned context
  with a synthetic Calendar page.

### Changed

- Marked the Version 1 design baseline ready for implementation beginning with
  Milestone 1 — Python Project Foundation.
- Clarified that design acceptance authorizes the defined implementation scope
  without claiming that the finished feature has passed operational
  acceptance.
- Marked Milestone 1 — Python Project Foundation complete and Milestone 2 —
  Core Domain and Persistence as next.
- Marked Milestone 2 — Core Domain and Persistence complete and Milestone 3 —
  Deterministic Briefing Pipeline as next.
- Marked Milestone 3 — Deterministic Briefing Pipeline complete and Milestone
  4 — First Safe Connectors as next.
- Recorded the authorized non-live Milestone 4 work as implemented and paused
  before the Google Calendar live-access approval gate.
