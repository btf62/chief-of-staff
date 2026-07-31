# Local State Operations

- **Status:** Draft
- **Owner:** Brad
- **Last updated:** 2026-07-31

This document describes the implemented local-state foundation and minimized
task-source extensions. It operates within
[ADR-0004](../decisions/0004-adopt-sqlite-and-bounded-local-data-lifecycle.md)
and does not authorize production data, backups, connector caching, or broader
product memory.

## Storage boundary

Chief of Staff uses one application-owned SQLite database. Lower-level state
operations require an explicit path; supported application commands use the
repository-local, ignored `.local/state.sqlite3` path by default and accept an
explicit override where documented. Database files and common SQLite suffixes
are ignored by Git.

Opening the database:

- Creates the parent directory when needed.
- Enables and verifies SQLite foreign-key enforcement.
- Applies pending packaged SQL migrations in version order.
- Verifies the name and SHA-256 checksum of every previously applied
  migration.
- Rejects unknown, reordered, duplicate, or modified migration history.

Migrations use explicit transactions. A failed migration or state mutation is
rolled back.

## Persisted records

The implemented schema stores:

- Connector-run metadata, approved scope descriptions, coverage, and
  freshness.
- Briefing-run metadata and connector-run associations.
- Minimal source references, optional bounded excerpts, and evidence
  fingerprints.
- Explicit or inferred conclusions with processing versions.
- Ordered conclusion-to-evidence links.
- Append-oriented correction and disposition events.
- Derived current-state projections with optimistic version protection.
- Structured local briefing presentations and minimized source links.
- Per-run generation time, effective `as_of` time, historical mode, processing
  versions, and originating-run lineage.
- Schema-versioned normalized facts needed for bounded replay, linked to the
  exact successful briefing run.
- Minimal conclusion-deletion tombstones containing only an evidence
  fingerprint, processing version, opaque idempotency key, and deletion time.
- Selected normalized Todoist task facts and only their referenced project,
  section, and label context.
- Selected normalized Jira issue facts, labels, and issue-link references.
- Minimized normalized Work Gmail message and thread facts for explicit
  detections, including direction, timestamp, classification, processing
  version, and only necessary local evidence.
- Non-content inference audit metadata: task, prompt, schema, policy, model
  configuration, provider and model identifiers, sensitivity and validation
  categories, request count, latency, token counts, estimated cost, and safe
  error category.
- One bounded Scheduled Morning trial policy and one non-content occurrence
  record per eligible local date: idempotency, eligibility decision, outcome,
  safe source-health categories, aggregate counts, duration, application
  version, notification result, and optional successful briefing-run link.

It does not define tables for credentials, tokens, raw response pages,
continuation cursors, full source payloads, complete message bodies, raw HTML,
attachments, connector caches, inference prompts, provider responses, or
inference evidence excerpts.

Scheduled occurrence payloads contain no source titles, message or task
content, people, account identities, URLs, provider payloads, or secret
values. A terminal occurrence is immutable. Only a `before_window` observation
may advance to the date's one terminal result.

## Briefing archive and historical lineage

Every successfully completed current, reduced-coverage, replayed, or
reconstructed briefing has a unique run identity. Multiple runs for one date
remain separate and are ordered by generation time. Failed or incomplete
attempts create neither a presentation nor archived facts.

Recorded presentations are immutable. Replay creates another run with current
processing versions and an explicit link to the originating recorded run.
Reconstruction is available only when approved historical evidence is
sufficient and excludes facts later than its effective `as_of`. Sources
without an honest as-of view are partial or unavailable. Synthetic scenarios
are evaluation artifacts and are not inserted into personal history.

Archived timestamps remain normalized to UTC for storage. Before replay or
reconstruction applies date-sensitive logic, it projects every archived
instant into the briefing run's recorded IANA timezone. That timezone governs
local day boundaries, temporal states, displayed times, due dates, schedule
gaps, and focus windows; a stored UTC representation never changes the source
event's local meaning.

Later corrections remain an explicit current overlay; the original recorded
statement remains distinguishable. A permitted local deletion removes the
dependent presentation content and matching replay facts while retaining only
the approved minimal recurrence tombstone.

## Inspection and recurrence

`StateStore.inspect_state()` returns non-content record counts and migration
versions. `StateStore.inspect_conclusion()` returns one conclusion, its ordered
source evidence, and its complete disposition history.

Recurrence projection uses the conclusion's material-evidence fingerprint:

- Unseen or confirmed evidence remains eligible to appear.
- Corrected evidence returns the approved replacement.
- Dismissed, delegated, rescheduled, completed, or intentionally abandoned
  evidence is suppressed while the fingerprint remains unchanged.
- Materially changed evidence receives a new fingerprint and may be
  reconsidered with an explanation that the material source evidence changed.
- A locally deleted conclusion remains suppressed while its minimal tombstone
  fingerprint is unchanged.

This is an explicit local overlay. It never changes an external source.

## Deletion and reset

The store supports:

- Deleting only a conclusion's disposition history.
- Deleting a conclusion and its dependent history.
- Deleting source evidence and any conclusion left without evidence.
- Deleting a briefing-run record.
- Pruning bounded connector- and briefing-run metadata.
- Pruning non-content inference audit metadata by creation time.
- Resetting all application-owned state while preserving migration history.

Reset includes Scheduled Morning trial and occurrence records. It is a
destructive local-state operation and is not a supported way to extend or
restart the bounded trial.

Deleting old run metadata does not delete still-useful correction evidence.
The relevant connector or briefing reference becomes `NULL`, while the
minimal provenance and recurrence state remain until explicitly deleted.

The Milestone 10 local-deletion transaction removes the conclusion statement,
dependent presentation item, disposition history, current-state projection,
and evidence payload when that evidence is not required by another
conclusion. It retains only a minimal non-sensitive fingerprint tombstone to
prevent unchanged recurrence. Shared authoritative evidence remains until it
is no longer referenced. A failed transaction rolls back the tombstone and
all deletion work together.

Deleting local state does not modify an authoritative external system.

## Current limitations

- Inspection and conclusion correction or deletion are available through the
  loopback-only local web interface. Lower-level retention and reset
  operations remain explicit Python APIs.
- Retention pruning requires an explicit caller and is not scheduled.
- Application-managed backup is disabled and undocumented by design.
- The repository contains no runtime database or production fixture.

Run the complete migration and lifecycle test suite with:

```text
make check
```
