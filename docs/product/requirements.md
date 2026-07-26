# Product Requirements

- **Status:** Accepted
- **Version:** 1
- **Owner:** Brad
- **Last updated:** 2026-07-25

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

## Delivery phases

| Phase | Intended outcome | Status |
| --- | --- | --- |
| [Daily Briefing v1](features/daily-briefing-v1.md) | A trusted daily starting point that clarifies today's outcomes, commitments, preparation, relationships, and approaching work | Accepted |

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
- Ideas explicitly deferred in [future ideas](future-ideas.md).

## Acceptance

This PRD is accepted as the Version 1 design contract. Design acceptance
authorizes implementation; it does not mean Daily Briefing v1 has passed its
feature acceptance criteria or is ready for operational use. That judgment
occurs after implementation and validation through the
[roadmap](../roadmap.md).
