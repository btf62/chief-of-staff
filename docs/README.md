# Documentation

This directory is the source of truth for project discovery, design, planning,
and future operations. Each subject has one authoritative location; other
documents should link to it instead of duplicating governing content.

## Current baseline

The Version 1 design baseline for Daily Briefing v1 is accepted. The
[implementation roadmap](roadmap.md) records Milestones 0 through 4 as
complete after an explicitly approved, bounded primary-calendar trial.
Milestone 5 has completed its accepted Todoist boundary, combined
Calendar-and-Todoist trial, and one explicitly approved complete-retrieval and
normal-workday quality validation. Jira has completed its mocked phase,
resource-restricted project discovery, and one explicitly approved
exact-project issue-retrieval trial integrated with a deterministic briefing.
Milestone 5 now covers only Todoist and Jira. Work Gmail is the final MVP input
connector. Its successful combined trial listed and inspected 357 messages,
found 144 eligible body candidates, selected 120, omitted 24 without body
retrieval, and produced 106 usable bodies. Gmail coverage was partial as
required while the other four inputs were complete. The trial created the
private review and a 929-word combined briefing. Brad reviewed the evidence
and explicitly judged the logic sound, completing Milestone 6. Milestone 7
precision-first deterministic detection passed its synthetic evaluation and
one five-source live validation. Brad reviewed the private evidence and
briefing and accepted the detections and supporting logic, completing
Milestone 7. Milestone 8's provider-neutral implementation, 25-scenario mocked
gate, and one bounded twenty-call synthetic Terra–Luna comparison are
complete. The comparison produced no false-positive actionable claims,
schema, provenance, provider, cache, or correction failures; three
moderate-uncertainty suggestions were safely rejected by deterministic policy.
Brad reviewed the category-specific results and selected OpenAI
`gpt-5.6-luna` with low reasoning for
`contextual_action_classification` only, completing Milestone 8. The one-time
authorization is consumed, the adapter remains disabled by default, and
routine hosted inference and private-data egress remain unauthorized. No
model is selected for ranking or synthesis. Personal Gmail and Google Drive
remain deferred and unauthorized. Milestone 9's deterministic ranking,
structured plan, canonical composition, and 26-scenario synthetic gate are
complete and accepted. Brad reviewed the corrected private representative
briefings after all scenarios passed with zero unsupported claims or
false-positive actionable recommendations. Conflict attribution, duplicate
suppression, authoritative links, source-backed ranking factors, and all
accepted presentation rules passed without a provider, connector, or
external-write operation.
Milestone 10's secure loopback-only reading and local correction experience is
complete and accepted. Brad reviewed the actual interface at normal browser
zoom, a successful five-source July 30 briefing, the correction controls and
evidence links, and its four-page PDF rendering. Milestone 11 operational
hardening is complete and accepted. On 2026-07-30, Brad reviewed and explicitly
approved the corrected historical behavior, preserved local times and lineage,
responsive and print presentations, partial-source behavior, privacy and
no-write boundaries, and all 14 synthetic metrics. Milestones 1–11 and the
on-demand Daily Briefing v1 MVP are therefore complete and accepted. Commit
`900a3b66d40bb3596e7ebee6ab801f5321050801` is the final correction included
in the accepted boundary. Scheduled generation and other deferred
capabilities remain unauthorized. Milestone 12 Scheduled Morning Generation
is now a proposed design and authorization gate, not an authorized
implementation.

## Index

### Product

- [Vision](product/vision.md) — product purpose, problem, desired outcomes,
  guiding purpose, and anti-goals
- [Product requirements](product/requirements.md) — top-level PRD, scope,
  phases, cross-feature requirements, and feature index
- [Feature specifications](product/features/README.md) — detailed,
  implementable product behavior
- [Daily Briefing v1](product/features/daily-briefing-v1.md) — first usable
  product milestone
- [Deterministic Explicit Detection v1](product/features/deterministic-explicit-detection-v1.md)
  — precision-first Milestone 7 commitment and preparation rules
- [Contextual Action Classification v1](product/features/contextual-action-classification-v1.md)
  — accepted Milestone 8 task contract and task-specific Luna selection
- [Ranking and Briefing Composition v1](product/features/ranking-and-briefing-composition-v1.md)
  — deterministic Milestone 9 ranking, planning, and composition contract
- [Scheduled Morning Generation v1](product/features/scheduled-morning-generation-v1.md)
  — proposed Milestone 12 automatic-invocation contract
- [Milestone 12 decision checklist](product/features/scheduled-morning-generation-decision-checklist.md)
  — the nine choices Brad must make before implementation
- [Future ideas](product/future-ideas.md) — valuable ideas explicitly outside
  current implementation scope

### Foundations

- [Constitution](foundations/constitution.md) — assistant judgment, behavior,
  boundaries, and tradeoffs
- [Leadership model](foundations/leadership-model.md) — primary-user horizons,
  responsibilities, rhythms, delegation, growth, and success measures

### Technical design

- [Architecture overview](architecture/overview.md) — overall technical
  architecture, system context, boundaries, and quality attributes
- [Connector specifications](architecture/connectors/README.md) — one
  specification per external source integration
- [Repository context connector](architecture/connectors/repository-context.md)
  — accepted exact-path local repository retrieval contract
- [Google Calendar connector](architecture/connectors/google-calendar.md) —
  accepted primary-calendar read boundary and bounded live-trial contract
- [Todoist connector](architecture/connectors/todoist.md) — accepted
  read-only task boundary and completed bounded live trial
- [Jira connector](architecture/connectors/jira.md) — accepted
  resource-restricted project discovery, exact-project enhanced search, and
  completed bounded issue trial
- [Work Gmail connector](architecture/connectors/gmail.md) — accepted final
  MVP input boundary; Personal Gmail deferred
- [Decision records](decisions/README.md) — architecture and significant
  product decisions
- [ADR-0009: Connector Authorization Continuity](decisions/0009-choose-connector-authorization-continuity.md)
  — proposed Milestone 12 credential-continuity dependency
- [ADR-0010: Scheduled Morning Generation Mechanism](decisions/0010-choose-scheduled-morning-generation-mechanism.md)
  — proposed macOS scheduling direction

### Delivery and operations

- [Implementation roadmap](roadmap.md) — Daily Briefing v1 milestones,
  dependencies, deliverables, acceptance gates, and excluded work
- [Operations](operations/README.md) — operational policies and deployment
  documentation
- [Local state operations](operations/local-state.md) — SQLite migration,
  inspection, deletion, reset, and recurrence behavior
- [Local web interface operations](operations/local-web.md) — loopback
  startup, shutdown, data location, diagnostics, and security controls
- [Deterministic briefing operations](operations/deterministic-briefing.md) —
  synthetic invocation, pipeline behavior, validation, and limitations
- [First safe connector operations](operations/first-safe-connectors.md) —
  safe demonstration, OAuth/Keychain boundaries, and bounded live-trial
  procedure
- [Runbooks](operations/runbooks/README.md) — step-by-step operational
  procedures
- [Run the on-demand briefing](operations/runbooks/on-demand-briefing.md) —
  supported local command and safe operating behavior
- [Milestone 8 live-evaluation gate](operations/milestone-8-live-evaluation-gate.md)
  — accepted and exercised OpenAI project, retention, cost, request, and
  synthetic-comparison boundary plus Brad's task-specific selection

### Repository guidance

- [`AGENTS.md`](../AGENTS.md) — canonical handoff and working instructions for
  Codex and future repository agents
- [Templates](../templates/) — reusable feature and decision-record formats

## Status vocabulary

- **Draft:** Incomplete and open for broad changes.
- **Proposed:** Ready for review.
- **Accepted:** Approved as the current source of truth.
- **Superseded:** Replaced by a newer document or decision.

## Maintenance

Each active document should identify its status, owner, and last-updated date.
Replace placeholders only with verified information, and link related decisions
where relevant.
