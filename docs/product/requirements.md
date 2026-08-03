# Product Requirements

- **Status:** Accepted
- **Version:** 8
- **Owner:** Brad
- **Last updated:** 2026-08-02

## Responsibility

This is the top-level product requirements document and requirements index. It
summarizes product scope, delivery phases, cross-feature requirements, and
links to detailed, implementable feature specifications.

Acceptance of this PRD authorizes implementation of the linked Daily Briefing
v1 scope within the accepted architecture and roadmap. It does not authorize
future ideas, deferred capabilities, or work identified as out of scope.

## Product scope

The first product phase is narrowly focused on
[Daily Briefing v1](features/daily-briefing-v1.md), a trustworthy,
approximately five-minute workday-morning briefing for Brad. It scans approved
sources, separates signal from noise, recommends priorities, identifies
preparation, surfaces commitments and people waiting on Brad, and shows
approaching work.

Daily Briefing v1 is read-only toward external systems and advisory. Source
systems remain authoritative; the product provides a unified interpretation
rather than replacing or modifying them. It may maintain bounded, inspectable
local state so Brad can correct or disposition inferred items and prevent
repeated false recommendations.

The accepted on-demand MVP input set is:

- Google Calendar
- Work Gmail
- Todoist
- Jira
- Approved repository context

Personal Gmail is the next accepted product-scope expansion after the bounded
Milestone 12 trial. [Milestone 13](../roadmap.md#milestone-13--personal-gmail-integration)
will add it as an isolated connector instance only after its access, privacy,
retrieval, retention, and human-review gates are complete. This decision does
not add Personal Gmail to the accepted on-demand MVP baseline or authorize
access during the active scheduled trial. Google Drive remains deferred and
unauthorized.

Adding another active MVP source requires an explicit product-scope decision
and its connector-specific access, privacy, and retention boundaries.

## Delivery phases

| Phase | Intended outcome | Status |
| --- | --- | --- |
| [Daily Briefing v1](features/daily-briefing-v1.md) | A trusted daily starting point that clarifies today's outcomes, commitments, preparation, relationships, and approaching work | Accepted |
| [Scheduled Morning Generation v1](features/scheduled-morning-generation-v1.md) | One reliable automatic morning invocation on approved days | Accepted — bounded trial implemented; activation gated |
| [Personal Gmail Integration](../roadmap.md#milestone-13--personal-gmail-integration) | An isolated personal-email input with precision-first conclusions and independent trust gates | Accepted and queued after Milestone 12 review |

## Cross-feature requirements

All product capabilities must:

- Remain subordinate to the [Vision](vision.md) and
  [Constitution](../foundations/constitution.md).
- Use the [Leadership Model](../foundations/leadership-model.md) as descriptive
  context rather than a fixed schedule or hidden scoring model.
- Preserve source-system authority and identify provenance, uncertainty, stale
  data, and conflicts.
- Minimize sensitive information and protect affected third parties.
- Present clarity rather than completeness.
- Stay within explicitly approved access and agency boundaries.
- Make persistent conclusions and local correction state inspectable,
  correctable, and deletable where technically possible.

## Feature index

| Feature | Specification | Status |
| --- | --- | --- |
| Daily Briefing v1 | [Specification](features/daily-briefing-v1.md) | Accepted |
| Deterministic Explicit Detection v1 | [Specification](features/deterministic-explicit-detection-v1.md) | Accepted |
| Contextual Action Classification v1 | [Specification](features/contextual-action-classification-v1.md) | Accepted |
| Ranking and Briefing Composition v1 | [Specification](features/ranking-and-briefing-composition-v1.md) | Accepted |
| Scheduled Morning Generation v1 | [Specification](features/scheduled-morning-generation-v1.md) | Accepted |

Detailed feature specifications belong in the
[feature specifications directory](features/README.md).

## Constraints

- Technology choices are governed by the accepted
  [technical architecture](../architecture/overview.md) and
  [decision records](../decisions/README.md).
- Implementation begins with synthetic data. Live data may be used only after
  the applicable connector, authorization, privacy, and retention boundaries
  are documented, tested, and explicitly approved.

## Out of scope

- Work outside the accepted
  [Daily Briefing v1 implementation roadmap](../roadmap.md).
- Rock RMS, Church Online Platform, ministry analytics, dashboards, and
  autonomous actions in Daily Briefing v1.
- Personal Gmail before the Milestone 13 implementation and acceptance gates,
  and Google Drive in the accepted on-demand MVP.
- Sources not included in the active MVP input set.
- Ideas explicitly deferred in [future ideas](future-ideas.md).
- Routine scheduled generation after Milestone 12's seven-eligible-date trial
  unless Brad explicitly accepts or extends it.

## Acceptance

This PRD is accepted as the Version 1 design contract. On 2026-07-30, Brad
separately accepted the implemented on-demand Daily Briefing v1 MVP after the
human-review gate in the [roadmap](../roadmap.md). That operational acceptance
does not authorize Personal Gmail before its Milestone 13 gates, Google Drive,
routine scheduled generation after the bounded Milestone 12 trial, routine
hosted inference, or external writes.
