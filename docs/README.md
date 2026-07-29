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
precision-first deterministic detection has passed its synthetic evaluation
and one five-source live validation. Its implementation is complete; Brad's
review of the private Milestone 7 evidence remains the acceptance gate.
Personal Gmail and Google Drive remain deferred and unauthorized.
Design acceptance authorizes implementation within the accepted scope; it does
not mean the complete Daily Briefing has passed operational acceptance.

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

### Delivery and operations

- [Implementation roadmap](roadmap.md) — Daily Briefing v1 milestones,
  dependencies, deliverables, acceptance gates, and excluded work
- [Operations](operations/README.md) — operational policies and deployment
  documentation
- [Local state operations](operations/local-state.md) — SQLite migration,
  inspection, deletion, reset, and recurrence behavior
- [Deterministic briefing operations](operations/deterministic-briefing.md) —
  synthetic invocation, pipeline behavior, validation, and limitations
- [First safe connector operations](operations/first-safe-connectors.md) —
  safe demonstration, OAuth/Keychain boundaries, and bounded live-trial
  procedure
- [Runbooks](operations/runbooks/README.md) — step-by-step operational
  procedures
- [Run the on-demand briefing](operations/runbooks/on-demand-briefing.md) —
  supported local command and safe operating behavior

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
