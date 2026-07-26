# Daily Briefing v1 Implementation Roadmap

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-25

This roadmap sequences implementation of the accepted
[Daily Briefing v1](product/features/daily-briefing-v1.md) design. Milestones 0
through 4 are complete. Milestone 4 concluded with one explicitly approved,
bounded primary-calendar trial; work is stopped before Milestone 5. Dates and
estimates remain intentionally omitted until implementation evidence supports
them.

Acceptance of this roadmap does not expand product scope. The
[Product Requirements](product/requirements.md), feature specification,
[Architecture Overview](architecture/overview.md), and accepted
[decision records](decisions/README.md) remain authoritative for behavior and
boundaries.

## Implementation principles

- Build vertical, testable slices.
- Use synthetic data before approved live data.
- Add one connector at a time.
- Keep deterministic processing independently testable.
- Do not begin with Gmail merely because it contains valuable information.
- Do not implement dashboards, Rock RMS, Church Online Platform, analytics,
  external actions, or multi-user behavior.
- Update documentation and ADRs when implementation reveals a material
  decision.

## Milestone 0 — Design Baseline

- **Status:** Complete
- **Intended user-visible outcome:** Brad and future contributors have one
  reviewed, internally consistent contract for what Daily Briefing v1 is and
  how it will be built; this milestone intentionally produces no application
  functionality.
- **Dependencies:** Repository documentation governance and Brad's review.
- **Principal deliverables:**
  - Accepted Vision, Constitution, Leadership Model, PRD, Daily Briefing v1
    feature specification, and Architecture Overview.
  - Accepted ADR-0001 through ADR-0006.
  - Validated documentation links, authority model, privacy boundaries, and
    implementation governance.
- **Acceptance gate:** Every baseline document has accepted metadata, all six
  ADRs are indexed, local Markdown links resolve, and no unresolved
  contradiction blocks Milestone 1.
- **Explicitly excluded work:** Application code, dependencies, schemas,
  runtime configuration, credentials, production connectors, and private
  data.

## Milestone 1 — Python Project Foundation

- **Status:** Complete
- **Intended user-visible outcome:** No end-user briefing yet; Brad and
  contributors can develop and validate the application through a consistent,
  safe, repeatable project workflow.
- **Dependencies:** Milestone 0 and
  [ADR-0003](decisions/0003-adopt-local-first-python-runtime.md).
- **Principal deliverables:**
  - Python package and module structure.
  - Supported Python-version policy.
  - Dependency and virtual-environment approach.
  - Formatting, linting, type checking, and testing.
  - Configuration boundary.
  - Structured redacted logging.
  - Developer commands and continuous integration.
  - No production connectors or private data.
- **Acceptance gate:** A clean checkout can use documented commands to set up
  the supported environment and run formatting, linting, type checking, and
  tests; configuration and logging tests demonstrate that secret-shaped or
  private values are not committed or emitted.
- **Explicitly excluded work:** Production connector authorization, live
  source access, private fixtures, database schema, briefing-domain behavior,
  hosted inference, and the user interface.

## Milestone 2 — Core Domain and Persistence

- **Status:** Complete
- **Intended user-visible outcome:** Brad's future corrections, dispositions,
  briefing runs, and provenance have an inspectable and deletable local
  foundation, demonstrated entirely with synthetic data.
- **Dependencies:** Milestone 1,
  [ADR-0004](decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md),
  and the conceptual information model in the Architecture Overview.
- **Principal deliverables:**
  - Application-owned domain models.
  - SQLite schema and migration process.
  - Connector-run and briefing-run records.
  - Provenance and evidence records.
  - Append-oriented correction and disposition history.
  - Inspection, deletion, and reset behavior.
  - Synthetic fixtures and tests.
- **Acceptance gate:** Fresh and upgraded databases migrate predictably;
  transactions and foreign keys are enforced; synthetic correction history
  can be inspected, projected, deleted, and reset; lifecycle tests enforce the
  accepted retention and external-source authority boundaries.
- **Explicitly excluded work:** Live source data, credentials, production
  connectors, complete source snapshots, application-managed backup,
  probabilistic inference, and user-interface design.

## Milestone 3 — Deterministic Briefing Pipeline

- **Status:** Complete
- **Intended user-visible outcome:** Brad can generate a reduced, factual,
  presentation-budget-compliant briefing from synthetic data without hosted
  inference.
- **Dependencies:** Milestone 2 and the Daily Briefing v1 canonical structure.
- **Principal deliverables:**
  - Workday and invocation context.
  - Read-only connector contract.
  - Normalization.
  - Source-coverage reporting.
  - Conservative deduplication primitives.
  - Structured briefing plan.
  - Presentation-budget validators.
  - Reduced briefing generation entirely from synthetic data.
- **Acceptance gate:** An end-to-end synthetic run produces a deterministic
  briefing with traceable evidence, correct section ordering, enforced item
  and word budgets, duplicate controls, partial-source disclosure, and no
  external writes.
- **Explicitly excluded work:** Live connector authorization, hosted
  inference, probabilistic ranking, production source content, scheduling, and
  a finished local web experience.

## Milestone 4 — First Safe Connectors

- **Status:** Complete
- **Intended user-visible outcome:** Brad can request a factual briefing that
  accurately shows approved repository context, today's calendar, and source
  coverage without hosted inference.
- **Dependencies:** Milestone 3,
  [ADR-0005](decisions/0005-adopt-oauth-and-macos-keychain.md), and accepted
  connector specifications for approved repository context and Google
  Calendar before live authorization.
- **Principal deliverables:**
  1. Approved local repository context connector.
  2. Google Calendar connector.
  3. Mocks and contract tests before approved live authorization.
  4. Connector health, freshness, coverage, provenance, and failure
     disclosure.
  5. On-demand factual briefing from those approved sources.
- **Acceptance gate:** Each connector passes read-only contract and
  authorization-boundary tests before live use; an approved on-demand run
  reports calendar and repository facts with authoritative links and clearly
  distinguishes unavailable, empty, stale, and unauthorized coverage.
- **Explicitly excluded work:** Gmail, Drive, task-system connectors, hosted
  inference, external writes, broad repository access, scheduled generation,
  and unapproved accounts or paths.

### Completion checkpoint

The accepted exact-path repository-context connector is implemented. The
Google Calendar connector has a retrieval-only interface, exact read-only
scope enforcement, installed-app OAuth with state and PKCE, native macOS
Keychain storage, primary-only live transport, pagination, partial-failure
handling, and no-write contract tests. An approved on-demand trial combined
repository-owned context with a bounded live primary-calendar window,
preserved minimal provenance and coverage, stayed within its presentation
budget, and used no hosted inference.

The trial is complete and live access is stopped. Continue only after a new
explicit approval for another Calendar retrieval or any later connector.

## Milestone 5 — Task-System Connectors

- **Status:** Planned
- **Intended user-visible outcome:** Brad's factual briefing can include
  relevant source-owned work across Todoist, Jira, and Asana without replacing
  any task system.
- **Dependencies:** Milestone 4 and an accepted connector specification for
  each task system before its live authorization.
- **Principal deliverables:**
  - Todoist connector.
  - Jira connector.
  - Asana connector.
  - Source-owned tasks, deadlines, ownership, and project context.
  - Preservation of conflicting source facts.
  - Conservative cross-source associations.
- **Acceptance gate:** Each connector independently passes mocked and live-
  authorization gates; task facts retain source identity and provenance;
  likely duplicates are associated without destructive merging; material
  conflicts remain visible.
- **Explicitly excluded work:** Gmail, Drive, model-based inference, task
  creation or modification, automatic conflict resolution, and broad
  cross-source identity claims.

## Milestone 6 — Gmail and Google Drive Connectors

- **Status:** Planned
- **Intended user-visible outcome:** Brad can include narrowly approved
  correspondence and document context in an on-demand briefing after the
  connector, persistence, redaction, and authorization boundaries are proven.
- **Dependencies:** Milestone 5, proven lifecycle and redaction behavior, and
  accepted Gmail and Google Drive connector specifications before live
  authorization.
- **Principal deliverables:**
  - Narrow approved scopes.
  - Retrieval windows and labels.
  - Sent-mail support.
  - Minimal excerpts.
  - No attachment processing unless separately specified.
  - Authentication-failure disclosure.
  - Connector-specific caching and retention decisions.
- **Acceptance gate:** Contract, sensitivity, minimization, retention, and
  revocation tests pass; approved live trials disclose coverage accurately and
  persist no broader content than the connector specifications permit.
- **Explicitly excluded work:** Attachments without a separate specification,
  entire-mailbox or Drive-corpus retrieval, write scopes, sending or editing,
  hosted inference, and silent cache expansion.

## Milestone 7 — Explicit Commitment and Preparation Detection

- **Status:** Planned
- **Intended user-visible outcome:** Brad receives conservative, explainable
  source-backed notice of directly stated commitments, preparation needs, and
  people explicitly waiting.
- **Dependencies:** Milestone 6 and representative synthetic scenarios for
  deterministic classification.
- **Principal deliverables:**
  - Deterministic and rules-based detection of direct requests.
  - Detection of explicit promises.
  - Detection of deadlines.
  - Detection of acknowledgment obligations.
  - Detection of meeting preparation.
  - Detection of people explicitly waiting.
  - Separate representations for explicit and inferred items.
- **Acceptance gate:** Human-reviewed scenarios demonstrate traceable,
  precision-oriented explicit detection; every included item links to evidence
  and the pipeline returns `insufficient evidence` rather than manufacturing a
  result.
- **Explicitly excluded work:** Contextual model inference, treating inferred
  claims as explicit, opaque scoring, production model selection, and
  automatic external action.

## Milestone 8 — Provider-Neutral Inference

- **Status:** Planned
- **Intended user-visible outcome:** Where permitted and demonstrably useful,
  Brad receives bounded contextual inference and synthesis with evidence,
  explanations, sensitivity controls, and a clear reduced-mode fallback.
- **Dependencies:** Milestone 7,
  [ADR-0006](decisions/0006-adopt-provider-neutral-inference-with-openai.md),
  approved inference-task specifications, current provider-policy
  verification, and representative evaluation data.
- **Principal deliverables:**
  - Application-owned inference schemas.
  - Sensitivity classification.
  - Evidence minimization.
  - OpenAI adapter behind the provider-neutral boundary.
  - Structured outputs.
  - Tier-based hosted-inference eligibility.
  - Prompt, model, schema, and policy versioning.
  - Deterministic reduced mode.
  - Representative evaluation harness.
- **Acceptance gate:** Comparative evaluation selects an approved production
  configuration; schema, provenance, egress, sensitivity, cost, timeout,
  fallback, and false-positive tests pass; hosted unavailability still
  produces an honest deterministic reduced mode.
- **Explicitly excluded work:** Selecting the production model before
  comparative evaluation, direct model access to sources or SQLite, provider
  memory, Tier 3 use under standard retention, silent provider fallback,
  fine-tuning on private data, and external-action tools.

## Milestone 9 — Ranking and Briefing Composition

- **Status:** Planned
- **Intended user-visible outcome:** Brad receives a concise, explainable
  briefing that separates signal from noise and directs attention to the most
  important supported outcomes.
- **Dependencies:** Milestone 8, accepted production inference configuration,
  and representative ranking and composition scenarios.
- **Principal deliverables:**
  - Explainable ranking factors.
  - Today's Outcomes.
  - Up Next.
  - People Waiting on Brad.
  - Commitments at Risk.
  - Preparation Needed.
  - Recommended Focus Block.
  - Looking Ahead.
  - Chief of Staff Note.
  - Provenance and confidence display.
  - Word and section budgets.
  - Duplicate suppression.
- **Acceptance gate:** Representative briefings satisfy the canonical
  structure, precision-first inclusion rules, authoritative-link and
  explanation requirements, 1,000-word maximum, ordinary item caps, and
  external-write prohibition without manufactured content.
- **Explicitly excluded work:** A dashboard, full inbox or task summaries,
  hidden scoring, unbounded prose, unsupported claims, autonomous action,
  scheduling, and multi-user presentation.

## Milestone 10 — Local Web Experience and Correction Loop

- **Status:** Planned
- **Intended user-visible outcome:** Brad can read the briefing, understand why
  each conclusion appeared, and correct or disposition local conclusions so
  materially unchanged mistakes do not recur.
- **Dependencies:** Milestone 9 and a documented local-web framework and
  interaction choice made when this milestone begins, unless an earlier
  implementation need requires it.
- **Principal deliverables:**
  - Read the briefing.
  - Inspect source evidence and inference explanations.
  - Confirm, correct, dismiss, delegate, reschedule, complete, intentionally
    abandon, or delete local conclusions.
  - Prevent repeated false inferences.
  - Inspect source coverage and connector health.
  - Keep all external systems read-only.
- **Acceptance gate:** End-to-end tests demonstrate every required disposition,
  inspectable history, recurrence prevention from materially unchanged
  evidence, explainable reappearance after material change, deletion behavior,
  local-only access, and zero external writes.
- **Explicitly excluded work:** Remote or public exposure, external-source
  mutation, mobile or multi-user interfaces, dashboards, scheduled delivery,
  and framework-driven architecture expansion.

## Milestone 11 — Acceptance and Operational Hardening

- **Status:** Planned
- **Intended user-visible outcome:** Brad can rely on an on-demand Daily
  Briefing v1 within its disclosed source coverage and privacy boundaries.
- **Dependencies:** Milestone 10, approved live connector access, and an
  explicitly owned acceptance corpus and review process.
- **Principal deliverables:**
  - Representative human-reviewed scenarios.
  - Separate precision measurement for People Waiting and Commitments at Risk.
  - Correction-regression testing.
  - Privacy and sensitivity testing.
  - External-write prevention tests.
  - Credential revocation and reauthorization tests.
  - Partial-source briefing behavior.
  - Retention and deletion verification.
  - On-demand Daily Briefing v1 acceptance.
- **Acceptance gate:** Brad approves representative results; required precision
  thresholds are met; false positives and repeated mistakes are reviewed;
  privacy, authorization, deletion, retention, degraded-mode, and no-write
  tests pass; operating documentation covers supported on-demand use.
- **Explicitly excluded work:** Scheduled morning generation, service-level
  promises for an always-on host, external actions, deferred source systems,
  analytics, and multi-user operation.

## Deferred Milestone — Scheduled Morning Generation

- **Status:** Deferred
- **Intended user-visible outcome:** After the on-demand briefing is
  trustworthy, Brad can receive reliable morning generation without manually
  invoking it.
- **Dependencies:** Milestone 11, a suitable awake and connected host, and a
  separately reviewed operational design.
- **Principal deliverables:**
  - Scheduler selection.
  - Host-reliability expectations.
  - Missed-run handling.
  - Duplicate-run prevention.
  - Operational monitoring.
- **Acceptance gate:** Scheduling, recovery, idempotency, monitoring, privacy,
  and host-failure behavior are documented, tested, and accepted before
  unattended use.
- **Explicitly excluded work:** Scheduling before on-demand trust is
  established, silent missed runs, duplicate briefing replacement, and an
  assumption that Brad's current Mac is always awake.
