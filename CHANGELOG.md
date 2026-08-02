# Changelog

All notable changes to this project will be documented here. The format is
inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

No strict versioning scheme is promised before a distributable product exists.

## [Unreleased]

### Changed

- Brad changed the bounded Milestone 12 trigger from 7:00 to 6:00 a.m.
  `America/New_York` without resetting or extending the seven-date trial.
- Scheduled generation now requires repository context, Calendar, and at least
  one of Work Gmail or Todoist; Jira remains optional, and repeated terminal
  outcomes cannot trigger a whole-run retry.
- Brad accepted the Milestone 12 operating decisions, exact source-sufficiency
  and connector-continuity boundaries, user-level LaunchAgent architecture,
  and implementation of a self-limiting seven-eligible-date trial.
- Brad accepted Milestone 11 and the on-demand Daily Briefing v1 MVP after
  reviewing the corrected historical behavior, responsive and print
  presentations, partial-source operation, privacy and no-write boundaries,
  and all 14 synthetic acceptance metrics.
- Historical replay and reconstruction now project UTC-normalized archived
  instants into the briefing's recorded IANA timezone before local-day
  classification, display, ranking, schedule-gap, and focus-window logic.
- The Milestone 11 historical gate now compares recorded and replayed local
  Calendar times, focus boundaries, briefing dates, source identifiers, and
  recorded-run lineage instead of passing when both outputs merely generate.

### Added

- Repository-native `make help`, `make commands`, and bare `make` command
  indexes for everyday, scheduled-trial, and development operations.
- A self-limiting Scheduled Morning Generation implementation with
  `America/New_York` eligibility and cutoff policy, immutable date
  idempotency, migration `0012`, private-safe notifications, local status,
  reversible current-user LaunchAgent management, exact-scope Calendar refresh
  continuity, synthetic tests, and an operator runbook.
- A passing 414-test repository gate, existing inference and ranking
  evaluations, Milestone 11 evaluation, Markdown validation, dry-run package,
  and clean wheel-install verification for the bounded scheduler.
- An accepted Milestone 12 Scheduled Morning Generation specification, macOS
  scheduling ADR, connector-authorization boundary, and nine-decision
  checklist. Routine unattended operation after the trial remains unaccepted.
- A private mode-`0600` Milestone 11 synthetic acceptance package covering
  representative day shapes, every single-source outage, historical lineage,
  safe source-title handling, responsive browser captures, print/PDF review,
  and 14 passing acceptance metrics.
- Whole-day temporal semantics with explicit briefing, generation, and
  effective-as-of times; written earlier, in-progress, and upcoming states;
  and preservation of elapsed or partly elapsed focus opportunities.
- Immutable structured briefing archives for every successful generation,
  including multiple runs per date, minimized replay facts, explicit recorded,
  replay, reconstructed, and synthetic lineage, correction overlays, and
  deletion-aware replay behavior.
- Retrieval-free approved-connector health inspection, connector-specific
  recovery guidance, safe preflight omission, and independent reduced-source
  operation.
- Supported `make web`, `make web-open`, `make connector-status`, and
  `make milestone-11-eval` commands for normal local operation and review.
- A loopback-only Flask and Jinja briefing interface served by Waitress, with
  strict Host and Origin enforcement, CSRF, request limits, optimistic
  versions, idempotency, response security headers, and no remote API or
  browser-held private state.
- Complete local confirm, correct, dismiss, delegate, reschedule, complete,
  intentionally abandon, and delete controls with inspectable history,
  current-state projection, recurrence behavior, and transactional minimal
  deletion tombstones.
- Forward-only migration 0010 for structured briefing presentation, complete
  disposition events, current-state projections, and deletion semantics.
- ADR-0008, selecting exact-pinned Flask and Waitress releases for a
  server-rendered, loopback-only local web interface within the existing
  Python and SQLite boundary.
- An accepted Ranking and Briefing Composition v1 specification, explainable
  qualitative priority bands with source-backed factors and deterministic tie
  behavior, correction-before-ranking, and untrusted priority-instruction
  exclusion.
- A formalized application-owned briefing plan retaining semantic content
  roles, selected outcomes, note inputs, correction and duplicate
  suppressions, conflicts, uncertainty, provenance, and coverage warnings.
- A 26-scenario Milestone 9 synthetic evaluation with five private mode-`0600`
  representative briefings and an aggregate report under ignored local state.
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
- Privacy-safe current-run Gmail failure audits with typed category, stage,
  stream, window, configured boundary, observed count, and lifecycle progress,
  plus private mode-`0600` per-attempt aggregate reporting without failed-run
  application-data persistence or briefing artifacts.
- The accepted `contextual_action_classification` specification and a
  provider-neutral inference boundary for unresolved candidates, with stable
  evidence references, minimized evidence packets, conservative sensitivity
  exclusion, deterministic validation, correction-state enforcement, and
  honest reduced-mode outcomes.
- A disabled-by-default, injected-transport OpenAI Responses adapter with
  strict application-owned Structured Outputs, `store=false`, no background
  mode or tools, explicit organization/project/model/retention controls,
  Keychain-only future credentials, bounded calls, and no silent fallback.
- Non-content inference audit persistence and lifecycle pruning, plus a
  25-scenario mocked evaluation reporting zero false positives, false
  negatives, or correction regressions.
- A Milestone 8 live-evaluation gate that keeps synthetic Tier 1 evaluation,
  API-key creation, billing, retention, model comparison, and any private-data
  egress behind explicit approval.
- An exact-pinned official OpenAI Python SDK transport for the disabled-by-
  default Responses adapter, with zero retries, a 20-second timeout, strict
  Structured Outputs, `store=false`, explicit cache control, and no tools or
  provider state.
- A twenty-call synthetic-only Terra–Luna comparison harness with application-
  owned cost, call, sensitivity, provenance, caching, and persistence
  boundaries plus a private mode-`0600` review artifact.

### Changed

- Corrected the local briefing header so deterministic logic and source
  coverage are reported independently; full coverage is no longer labeled
  reduced merely because hosted inference is disabled.
- Sanitized link-like and HTML-like source titles into readable non-executable
  text while retaining only the source system's authoritative link.
- Added conservative print rules that keep notes and items together when
  practical, avoid isolated section headings, and subordinate interactive
  review links.
- Accepted Brad's review of the actual Milestone 10 interface at normal
  browser zoom, a successful five-source July 30 briefing, the correction
  controls and evidence links, and the four-page PDF rendering, completing the
  local web and correction-loop trust gate.
- Accepted Brad's review of the corrected Milestone 9 representative
  briefings, completing the ranking and composition trust gate after all 26
  scenarios passed with zero unsupported claims or false-positive actionable
  recommendations and without provider, connector, or external-write
  operations.
- Qualified cross-source deadline, owner, status, priority, and completion
  conflicts with source-attributed values instead of presenting one
  representative value as canonical.
- Replaced internal ranking labels and mechanical Calendar-span prose with
  natural factor explanations, separate-block schedule summaries, and
  reusable singular/plural count formatting.
- Brad selected OpenAI `gpt-5.6-luna` with low reasoning and the exact
  evaluated Responses configuration for
  `contextual_action_classification` only, completing Milestone 8. The adapter
  remains disabled by default, no ranking or synthesis model is selected, and
  no new provider call or private-source egress is authorized.
- Accepted and exercised the Milestone 8 live-evaluation gate. All twenty
  synthetic calls completed with zero false-positive actionable claims,
  schema, provenance, provider, cache, or correction failures; deterministic
  policy safely rejected three moderate-uncertainty suggestions. The
  comparison authorization is consumed, and routine hosted inference remains
  unauthorized.
- Accepted Brad's Milestone 7 private evidence and briefing review, completing
  the precision-first deterministic trust gate. Every displayed conclusion
  remains evidence-linked, unsupported candidates remain
  `insufficient_evidence`, local corrections and dismissals remain
  authoritative, and the accepted run used no hosted inference.
- Accepted Brad's private Work Gmail evidence review and explicit judgment that
  the results and logic are sound, completing the Milestone 6 trust gate.
- Added the supported `make briefing` on-demand command with private artifacts,
  safe partial-coverage output, failure diagnostics, and duplicate-run locking.
- Accepted the Milestone 7 deterministic explicit-detection specification and
  began precision-first deadline, acknowledgment, preparation, evidence-
  classification, recurrence, and synthetic-evaluation behavior.
- Completed Milestone 7's deterministic implementation, representative
  synthetic evaluation, and one five-source live validation. The live run
  created private mode-`0600` review and briefing artifacts, remained
  read-only, and used no hosted inference.
- Replaced the mixed Work Gmail trial query with separate seven-day inbound and
  fourteen-day sent streams, independent 300/200 message caps, combined
  immutable-ID deduplication, a 120-body-candidate cap, and per-stream coverage.
- Replaced the all-or-nothing body-candidate stop with deterministic,
  proportional inbound/sent selection of at most 120 recent candidates,
  transparent partial coverage, aggregate omission accounting, and graceful
  extracted-content exhaustion without truncated conclusions.
- Completed the same-window combined Work Gmail MVP trial with partial Gmail
  coverage, minimized persistence, a private candidate review, and a
  budget-compliant deterministic briefing; stopped live access pending Brad's
  private trust review.
- Recorded that the first combined Work Gmail trial stopped without producing
  Gmail records, persisted briefing state, a review artifact, or a combined
  briefing; Milestone 6 remains in progress.
- Recorded Brad's authorization for repeatable, on-demand, read-only Work
  Gmail validation within the accepted account, scope, privacy, and source
  boundaries until an MVP briefing succeeds or a genuine external blocker is
  reached; identical bounded attempts need no separate approval.
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
