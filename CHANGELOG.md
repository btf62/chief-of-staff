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

### Changed

- Marked the Version 1 design baseline ready for implementation beginning with
  Milestone 1 — Python Project Foundation.
- Clarified that design acceptance authorizes the defined implementation scope
  without claiming that the finished feature has passed operational
  acceptance.
- Marked Milestone 1 — Python Project Foundation complete and Milestone 2 —
  Core Domain and Persistence as next.
