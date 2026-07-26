# Documentation

This directory is the source of truth for project discovery, design, planning,
and future operations. Each subject has one authoritative location; other
documents should link to it instead of duplicating governing content.

## Current baseline

The Version 1 design baseline for Daily Briefing v1 is accepted. The
[implementation roadmap](roadmap.md) records Milestones 0 and 1 as complete
and Milestone 2 — Core Domain and Persistence as next. Design acceptance
authorizes implementation within the accepted scope; it does not mean the
feature has passed operational acceptance.

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
- [Decision records](decisions/README.md) — architecture and significant
  product decisions

### Delivery and operations

- [Implementation roadmap](roadmap.md) — Daily Briefing v1 milestones,
  dependencies, deliverables, acceptance gates, and excluded work
- [Operations](operations/README.md) — operational policies and deployment
  documentation
- [Runbooks](operations/runbooks/README.md) — step-by-step operational
  procedures

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
