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
- Installed-app Google OAuth with state validation, PKCE, exact-scope
  enforcement, and short-lived authorization for a bounded Calendar trial.
- Native macOS Keychain storage for OAuth client secrets and access tokens,
  with only non-secret authorization metadata retained in SQLite.
- A primary-calendar-only HTTP transport with bounded windows, pagination,
  minimized event normalization, transient raw payloads, and no mutation
  methods.
- A deterministic bounded-trial runner that stores minimal provenance and
  coverage locally and writes private briefing output under ignored local
  state.
- Synthetic live-boundary tests for Keychain isolation, OAuth scope handling,
  primary-only retrieval, authorization failures, pagination, data lifecycle,
  and presentation budgets.
- Deterministic briefing rules and tests separating governing context from
  display content, protecting non-workdays, classifying Calendar events,
  synthesizing timestamp-obvious schedule implications, and placing source
  coverage outside the Chief of Staff Note.
- Provider-backed Calendar status signals and deterministic tomorrow-morning
  sequence synthesis that preserves individual event provenance.
- An accepted Todoist connector with exact `data:read` authorization,
  state-protected loopback OAuth, Keychain-only client and token storage,
  refresh rotation, revocation boundaries, and safe credential inspection.
- A bounded Todoist live transport for current-user confirmation, selected
  active tasks, referenced project and section context, necessary labels,
  cursor pagination, partial failures, and no mutation operations.
- Minimal normalized Todoist task persistence with source provenance,
  authoritative links, freshness, resolved context, and cascading label
  lifecycle.
- A combined deterministic live-trial runner for approved repository context,
  primary Calendar, and Todoist, with private output, transient raw payloads,
  independent coverage, and no hosted inference.
- An accepted Jira connector specification, mocked OAuth state boundary,
  read-only-only synthetic transport, typed issue normalization, conservative
  cross-source association, coverage funnel, and deterministic briefing
  integration stopped before live access.
- A resource-restricted Jira 3LO flow with exact `read:jira-work`, Keychain-
  only secrets, one-site binding, bounded project-only discovery, a private
  selection report, and a mandatory gate before issue access.
- An exact-project Jira enhanced-search transport with fixed JQL and fields,
  cursor pagination, minimized parsing, distinct failures, and no mutation
  operations.
- Dedicated normalized Jira issue, label, and issue-link persistence with
  transient raw pages and continuation tokens.
- Conservative explicit-key Jira–Todoist association that preserves both
  source records, links, and conflicting facts while avoiding duplicate
  recommendations.
- One bounded combined repository, primary Calendar, Todoist, and Jira
  deterministic briefing trial without hosted inference or external writes.
- An explicit multi-account connector-instance model with independent
  authorization, Keychain references, configuration, domain, coverage,
  freshness, retention, and provenance.
- A preliminary two-account Gmail specification preserving strict work and
  personal domain boundaries without implementing or authorizing Gmail.
- An accepted Asana specification, synthetic task contract, exact-scope OAuth
  flow, bounded workspace/project discovery surface, private selection report,
  and no-mutation contract tests.
- ADR-0007, recording the decision to remove Asana from product scope.
- An accepted Work Gmail connector specification with exact scope, account,
  metadata-first retrieval, minimization, deterministic detection, persistence,
  review-artifact, and live-trial boundaries.
- A read-only Work Gmail implementation with dedicated installed-app OAuth,
  state and PKCE validation, exact-account enforcement, instance-specific
  Keychain credentials, refresh, revocation, and fixed Gmail API endpoints.
- Bounded metadata-first Gmail retrieval with stable pagination, message and
  candidate caps, inert MIME minimization, no attachment or raw-message path,
  high-precision request and promise rules, local correction recurrence, and
  canonical briefing integration.
- Minimized normalized Gmail persistence and private mode-`0600` review and
  input-complete briefing trial artifacts under ignored local state.

### Changed

- Replaced the mixed Work Gmail trial query with separate seven-day inbound and
  fourteen-day sent streams, independent 300/200 message caps, combined
  immutable-ID deduplication, a 120-body-candidate cap, and per-stream coverage.
- Recorded that the authorized combined Work Gmail trial was attempted and
  consumed without producing Gmail records, persisted briefing state, a review
  artifact, or a combined briefing; Milestone 6 remains in progress and live
  validation is paused pending offline diagnostic remediation.
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
- Completed the explicitly approved Milestone 4 bounded live Calendar trial
  and stopped before Milestone 5 or any additional live connector.
- Completed the explicitly approved bounded Todoist trial and stopped before
  Jira, another connector, or repeat Calendar or Todoist access.
- Completed Jira's mocked and synthetic-data phase and stopped at its mandatory
  live-access approval gate.
- Completed one bounded Jira authorization and project-discovery trial and
  stopped before project selection or live issue retrieval.
- Completed one bounded exact-project Jira issue trial and stopped before
  Asana, another connector, or any repeat live retrieval.
- Completed one bounded Asana OAuth and workspace-discovery trial; multiple
  accessible workspaces caused the required stop before project or task
  retrieval.
- Completed one explicitly approved Asana active-project discovery inside the
  selected organization workspace and stopped before task retrieval.
- Corrected the active Asana boundary to one explicitly approved exact project,
  superseded the earlier workspace selection, and stopped before task
  retrieval.
- Clarified that the superseded Northridge boards are obsolete and the exact
  project exists only for 9 Embers collaboration on Rock RMS development.
- Made Work Gmail the final MVP input connector and Milestone 6 input-complete
  briefing gate; deferred Personal Gmail and Google Drive until after MVP
  validation while preserving the multi-account design.

### Removed

- Asana from Daily Briefing v1, the Phase 1 source set, architecture, roadmap,
  operations, connector index, implementation, and tests.
- The local Asana OAuth grant, Keychain credentials, SQLite metadata, and
  private discovery reports. No live task data had been retrieved or
  persisted.
