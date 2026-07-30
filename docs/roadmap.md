# Daily Briefing v1 Implementation Roadmap

- **Status:** Accepted
- **Version:** 11
- **Owner:** Brad
- **Last updated:** 2026-07-30

This roadmap sequences implementation of the accepted
[Daily Briefing v1](product/features/daily-briefing-v1.md) design. Milestones 0
through 4 are complete. Milestone 4 concluded with one explicitly approved,
bounded primary-calendar trial. Milestone 5 has completed its accepted Todoist
boundary, combined Calendar-and-Todoist trial, and one explicitly approved
complete-retrieval and normal-workday quality validation. Jira has completed
its mocked phase, project discovery, and one exact-project live issue trial.
Milestone 5 now covers only the accepted Todoist and Jira task-system sources
and is complete. Milestone 6 completed the Work Gmail input gate and Brad's
human trust review. Milestone 7 deterministic explicit detection passed its
synthetic evaluation and one five-source live validation. Brad reviewed the
private evidence and briefing and accepted the detections and supporting
logic, completing Milestone 7. Brad reviewed Milestone 8's synthetic, mocked,
and bounded live comparison results and selected OpenAI `gpt-5.6-luna` with
low reasoning for `contextual_action_classification` only, completing
Milestone 8. Brad reviewed and accepted Milestone 9's corrected
representative briefings after its deterministic ranking, structured plan,
composition, and 26-scenario synthetic evaluation passed. Personal Gmail and
Google Drive are deferred until after MVP validation.
Dates and estimates remain intentionally omitted until implementation
evidence supports them.

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
- Treat Work Gmail as the final MVP input gate; do not expand into Personal
  Gmail or Google Drive before MVP validation.
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

- **Status:** Complete
- **Intended user-visible outcome:** Brad's factual briefing can include
  relevant source-owned work across Todoist and Jira without replacing either
  task system.
- **Dependencies:** Milestone 4 and an accepted connector specification for
  each task system before its live authorization.
- **Principal deliverables:**
  - Todoist connector.
  - Jira connector.
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

### Current checkpoint

The accepted [Todoist connector](architecture/connectors/todoist.md) now has a
retrieval-only live transport, exact `data:read` OAuth enforcement,
state-protected loopback authorization, Keychain-only client and token
storage, tested refresh and revocation boundaries, complete active-task
retrieval, context resolution, normalized local persistence, cursor
pagination, partial-failure handling, and no-write contract tests.

One explicitly approved on-demand trial combined the approved repository
context, bounded primary Calendar, and bounded Todoist sources. It generated a
private deterministic briefing, persisted only the accepted minimized facts
and run graph, kept raw payloads transient, and used no hosted inference or
other connector.

A later approved validation retrieved all active tasks, verified endpoint
priority semantics, reconciled the existing local snapshot, and generated
Sunday ministry-workday and Monday normal-workday briefings from one live
snapshot. The quality gate now distinguishes retrieval, selection,
persistence, daily-candidate, and display counts.

The accepted [Jira connector](architecture/connectors/jira.md) now has a
resource-restricted OAuth application, exact read-scope enforcement,
Keychain-only credentials, one-site binding, project-only discovery,
exact-project enhanced JQL search, minimized issue persistence, conservative
cross-source association, cursor pagination, failure handling, and
deterministic briefing integration.

One explicitly approved trial authorized the confirmed account, discovered one
selected Jira Cloud site, and retrieved only browse-visible minimal project
metadata. A later explicitly approved trial executed only the accepted `NRC`
query, persisted the approved normalized issue facts and provenance, and
generated one normal-workday briefing from live repository, primary Calendar,
Todoist, and Jira context without hosted inference. Jira items were not forced
into the briefing when current evidence did not support daily relevance.

Milestone 5 is complete. Repeat Jira retrieval, authorization refresh,
Calendar access, or Todoist access remains unauthorized without a new explicit
approval.

## Milestone 6 — Work Gmail and the Input-Complete MVP Gate

- **Status:** Complete
- **Intended user-visible outcome:** Brad can review one input-complete,
  on-demand MVP briefing that adds high-confidence work correspondence,
  explicit requests, and explicit sent commitments to the existing Calendar,
  Todoist, Jira, and repository context.
- **Dependencies:** Milestone 5, proven lifecycle and redaction behavior, and
  the accepted [Work Gmail connector](architecture/connectors/gmail.md)
  specification.
- **Principal deliverables:**
  - One independently authorized `Work Gmail` connector instance.
  - Exact `gmail.readonly` scope, installed-app OAuth, Keychain-only secrets,
    account confirmation, refresh, revocation, and disconnection.
  - Separate bounded seven-day inbound and fourteen-day sent streams with
    metadata-first candidate selection, stream-specific caps, and cross-stream
    deduplication.
  - Minimized MIME parsing without attachments, active content, remote
    resources, or raw-message retrieval.
  - Deterministic high-precision explicit-request, reply-state, explicit-
    commitment, and at-risk detection.
  - Minimal local persistence, provenance, coverage, and deletion.
  - Private candidate-review artifact.
  - One fresh combined repository, Calendar, Todoist, Jira, and Work Gmail
    briefing without hosted inference.
- **Acceptance gate:** All synthetic contract, security, minimization,
  persistence, and regression tests pass; one approved live trial preserves
  the exact account and scope, discloses coverage, persists only minimized
  evidence, and produces a private review artifact and input-complete briefing
  for Brad's human trust review.
- **Explicitly excluded work:** Personal Gmail, Google Drive, attachments,
  entire-mailbox retrieval, write scopes, sending or editing, hosted inference,
  scheduling, user-interface work, and operational MVP acceptance.

### Current checkpoint

The Work Gmail specification and synthetic implementation gate are complete.
Exact-scope OAuth, metadata-first retrieval, MIME minimization, high-precision
deterministic detection, minimized persistence, correction recurrence, private
review artifacts, and briefing integration passed the synthetic quality gate.
The successful same-window combined trial on 2026-07-28 listed and inspected
357 messages across four pages. It found 144 eligible body candidates,
selected 120, omitted 24 without body retrieval, attempted 117 body reads, and
produced 106 usable bodies. Gmail coverage was partial as required; repository,
primary Calendar, Todoist, and Jira coverage was complete. Three minimized
Gmail conclusions were persisted, two People Waiting items were displayed, and
the trial produced the private review plus a 929-word combined briefing.

The connector kept the 120-body privacy boundary. Coverage and the private
review disclosed aggregate selection and omission counts, no extracted-content
exhaustion occurred, and no truncated conclusion was used. Structural review
confirmed authoritative links and no quoted-history markers in minimal
evidence. Brad reviewed the private evidence and combined briefing and
explicitly judged the results and logic sound. That judgment completes the
Milestone 6 trust gate. Personal Gmail, Google Drive, hosted inference, and
another connector remain unauthorized.

## Milestone 7 — Explicit Commitment and Preparation Detection

- **Status:** Complete
- **Intended user-visible outcome:** Brad receives conservative, explainable
  source-backed notice of directly stated commitments, preparation needs, and
  people explicitly waiting.
- **Dependencies:** Completed Milestone 6 and representative synthetic scenarios for
  deterministic classification beyond the high-precision Work Gmail rules
  completed at the input gate.
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

The synthetic evaluation and automated regression gates pass. A 2026-07-29
five-source live run generated a private mode-`0600` evidence review and a
635-word briefing. Work Gmail selected all 118 eligible bounded body
candidates, produced 105 usable bodies, and disclosed partial coverage for 13
unavailable or unsupported bodies. Repository, Calendar, Todoist, and Jira
retrieval completed. The run remained read-only and did not use hosted
inference. Brad reviewed the private evidence and briefing and accepted the
detections and supporting logic. Every displayed conclusion remains
evidence-linked; unsupported candidates return `insufficient_evidence`; and
local corrections and dismissals remain authoritative for materially
unchanged evidence.

## Milestone 8 — Provider-Neutral Inference

- **Status:** Complete
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

The application-owned `contextual_action_classification` boundary now accepts
only unresolved contextual candidates, enforces conservative sensitivity and
evidence limits, validates strict structured results, preserves local
correction authority, and records non-content audit metadata. The OpenAI
Responses adapter remains disabled by default and now has an official-SDK
transport with explicit project, model, retention, caching, timeout, retry, and
state controls. The 25-scenario mocked evaluation reports three true positives,
five correct exclusions, three insufficient-evidence results, four sensitivity
or secret exclusions, and zero false positives, false negatives, or correction
regressions.

One explicitly approved 2026-07-29 comparison used a dedicated
Northridge-controlled project, a Responses-only service account, Keychain-only
credentials, a $1 provider hard limit, and an independent $1 application cap.
It sent ten synthetic Tier 1 scenarios once to Terra and once to Luna. All
twenty calls completed with zero false-positive actionable claims, schema
failures, provenance failures, provider failures, cache reads, cache writes,
or correction regressions. The application safely rejected three
moderate-uncertainty actionable suggestions. Total estimated cost was
$0.030177.

Brad reviewed the category-specific results and selected OpenAI
`gpt-5.6-luna` with low reasoning for
`contextual_action_classification` only. Luna produced zero false-positive
actionable claims, fewer false negatives than Terra, correct
`insufficient_evidence` behavior in conflicting and adversarial scenarios,
successful schema, provenance, policy, correction, and provider gates,
slightly lower latency, and lower bounded cost. This task-specific selection
completes and accepts Milestone 8.

The one-time authorization is consumed. The adapter remains disabled by
default. The selection does not apply to ranking or synthesis and does not
authorize another provider call, private-source evidence, or routine hosted
inference.

## Milestone 9 — Ranking and Briefing Composition

- **Status:** Complete
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

The accepted
[Ranking and Briefing Composition v1](product/features/ranking-and-briefing-composition-v1.md)
contract is implemented deterministically. Qualitative priority bands retain
source-backed factors and documented ties; corrections apply before ranking;
the structured plan preserves content roles, duplicate suppressions,
conflicts, coverage warnings, and note inputs; and the composer retains
canonical sections, links, focus margin, and presentation budgets.

The local evaluation gate passed 26 representative synthetic scenarios with
zero unsupported claims, false-positive actionable recommendations, provider
calls, live connector calls, or external writes. Conflict claims are
source-attributed; duplicate suppression preserves authoritative records and
links; ranking factors remain inspectable and source-backed; and the word,
section, outcome, focus-block, and canonical-order rules passed. Five
representative briefings and the aggregate report are retained under ignored,
private local state.

Brad reviewed the corrected representative briefings and explicitly accepted
Milestone 9. Minor presentation refinements may continue without reopening
this trust gate. No model is selected for `priority_comparison` or
`briefing_section_synthesis`.

## Milestone 10 — Local Web Experience and Correction Loop

- **Status:** Complete and accepted
- **Intended user-visible outcome:** Brad can read the briefing, understand why
  each conclusion appeared, and correct or disposition local conclusions so
  materially unchanged mistakes do not recur.
- **Dependencies:** Milestone 9 and
  [ADR-0008](decisions/0008-adopt-flask-local-web-interface.md).
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

The Flask and Jinja interface is implemented over the existing application and
SQLite boundary, with Waitress bound only to `127.0.0.1`. It presents the
latest structured briefing, minimized evidence, explanations, uncertainty,
source links, freshness, and coverage without exposing database identifiers or
raw private payloads. Every mutation is a local-only POST protected by exact
Host and strict Origin validation, session-bound CSRF, request limits,
optimistic versioning, idempotency, and post/redirect/get.

All required dispositions are implemented with complete timestamped history
and a derived current-state projection. Unchanged dismissed, corrected,
delegated, rescheduled, completed, or intentionally abandoned evidence follows
the local disposition; materially changed evidence may reappear with an
explanation. Transactional deletion removes conclusion payload, dependent
presentation and unshared evidence, and history while retaining only the
minimal fingerprint tombstone needed to prevent unchanged recurrence.

The synthetic UI and security matrix covers normal, partial, unavailable,
inferred, explicit, conflicting, corrected, dismissed, completed,
changed-evidence, empty, long-content, and malicious-text states without live
retrieval, provider calls, or external writes.

Brad reviewed the actual local interface at normal browser zoom, a successfully
generated five-source July 30 briefing, the correction controls and evidence
links, and the four-page PDF rendering. He assessed the result as “Looking
good,” explicitly accepting Milestone 10.

## Milestone 11 — Acceptance and Operational Hardening

- **Status:** In progress — local and synthetic review gate
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
