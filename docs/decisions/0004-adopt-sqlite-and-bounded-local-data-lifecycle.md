# ADR-0004: Adopt SQLite and a Bounded Local Data Lifecycle

- **Status:** Accepted
- **Date:** 2026-07-25
- **Owners:** Brad

## Context

[Daily Briefing v1](../product/features/daily-briefing-v1.md) requires
persistent local state for:

- Corrections and dispositions
- Prevention of repeated false inferences
- Briefing runs and versions
- Connector coverage and freshness
- Provenance and source references
- Inspectable local conclusions
- Evaluation and regression support

The system must preserve enough history to explain its behavior without
creating an unnecessary private archive of Gmail, Drive, Calendar,
task-system, or ministry content.

This decision applies within the local-first, single-user, one-process
deployment established by
[ADR-0003](0003-adopt-local-first-python-runtime.md).

## Decision drivers

- Preserve an inspectable correction history and prevent repeated mistakes.
- Keep external systems authoritative rather than creating shadow copies.
- Minimize the amount and lifetime of sensitive source content.
- Support transactions, relational integrity, explicit migrations, and
  testable deletion without unnecessary operational infrastructure.
- Keep local state portable between Brad's current Mac and a future Mac mini.
- Make retention, inspection, deletion, and backup behavior understandable to
  Brad.

## Options considered

### Option 1: PostgreSQL

PostgreSQL would provide stronger concurrent-write behavior and a more direct
path to a hosted, multi-user deployment. It was not selected for Version 1
because running and maintaining a database service adds operational complexity
without a single-user or one-process requirement that justifies it.

### Option 2: Flat JSON or Markdown files

Flat files would be transparent and simple for a tiny prototype. They were not
selected because relational integrity, transactions, migrations, querying,
append-oriented event history, derived projections, and reliable deletion
become harder as state and relationships grow.

### Option 3: Persist complete source snapshots

Complete snapshots would improve reproducibility and offline analysis. They
were rejected as the default because they would duplicate large amounts of
private source content and create a sensitive archive beyond what the briefing
needs.

### Option 4: No persistent state

An entirely transient system would have the smallest storage footprint. It was
rejected because corrections, dispositions, recurrence prevention,
inspectability, briefing history, and regression evaluation require durable
local state.

## Decision

### SQLite persistence

SQLite is the initial persistence layer. The single-user, one-process
application will maintain one application-owned local database.

The implementation must use transactions, enforce foreign keys, and apply
explicit schema migrations. Repository code and database schema definitions
belong in Git, but runtime database files belong outside Git. The persistence
model will not be designed for multi-user tenancy or distributed concurrency.

This ADR selects the persistence technology and lifecycle boundaries; it does
not define the database schema.

### Persistent data classes

The persistence model and related operational storage must distinguish at
least:

- Source references and minimal normalized facts
- Connector-run and coverage metadata
- Inferred commitments and waiting items
- Recommendations and briefing versions
- Correction and disposition events
- Derived current-state projections
- Redacted operational logs or audit metadata
- Application configuration references

Credentials and access tokens must not be stored in SQLite.

### Append-oriented correction history

Corrections and dispositions are stored as timestamped events. Current state is
derived from those events rather than produced by destructively replacing
history.

The event history is append-oriented, not absolutely immutable. Privacy and
deletion requests must be able to remove sensitive payloads, searchable
content, and dependent indexes. A minimal non-sensitive tombstone or evidence
fingerprint may remain only when it is necessary to prevent recurrence and the
deletion policy permits it.

### Minimal source persistence

The application does not persist full email bodies, attachments, Drive
documents, or complete source payloads by default. It prefers stable source
identifiers, authoritative links, timestamps, freshness, structured facts,
evidence fingerprints, and minimal excerpts.

Evidence excerpts are limited to what is necessary to explain an inference or
recommendation. Raw connector payloads normally exist only transiently during
a briefing run.

A connector specification may justify narrowly bounded caching when repeated
retrieval would be unreliable, expensive, or insufficient for provenance. The
specification must define what is cached, why it is necessary, its retention
period, and how it is deleted.

### Retention classes

Retention periods are configurable and favor the shortest period consistent
with product reliability, explanation, and recovery. The initial defaults are:

| Data class | Initial policy |
| --- | --- |
| Raw transient retrieval data | Keep only for the active run; delete at successful completion. Clean up crash or failure remnants within 24 hours. |
| Temporary source cache | Disabled by default. When a connector specification explicitly enables it, expire it after 24 hours unless a shorter or differently bounded period is justified. |
| Connector-run metadata and redacted operational logs | Retain for 30 days. |
| Generated briefing versions | Retain for 30 days for review and comparison. |
| Corrections, dispositions, identity corrections, and recurrence-prevention state | Retain only while operationally useful, until Brad deletes them, or until the related source context is retired. Review orphaned state at least annually. |
| Derived current-state projections | Rebuildable from retained events; never retain longer than the state from which they are derived. |
| Application configuration references | Retain while the referenced configuration is active; never include credentials or tokens. |
| Synthetic committed fixtures | Retain in Git under repository review. |
| Private evaluation scenarios | Keep access-controlled with an explicit owner and deletion path; expire after 90 days unless continued retention is reviewed and approved. |

Connector specifications may set shorter periods or justify a narrowly bounded
exception. They may not silently broaden these defaults.

### Inspection and deletion

Brad must be able to:

- Inspect persistent local conclusions
- Inspect correction and disposition history
- Delete individual conclusions or histories
- Delete briefings and cached source material
- Reset local product state
- Understand what remains after deletion and why

Deletion removes dependent searchable content and indexes. It does not modify
authoritative external systems. Deletion behavior must be testable, including
the removal or documented retention of any permitted non-sensitive tombstone.

### Encryption and host security

Version 1 relies on macOS account security and full-disk encryption as baseline
host protection. Full-disk encryption does not by itself resolve application,
backup, export, remote-access, or deletion risk.

The project will not implement custom cryptography without a demonstrated
requirement. Application-level database encryption will be reconsidered if the
threat model, backup method, or remote-access design requires it.

### Backup policy

Backups are optional, deliberate, and encrypted. They never include
credentials, access tokens, or transient raw retrieval payloads. Before the
first backup is enabled, operational documentation must identify whether the
SQLite database, generated briefings, corrections, and private evaluation data
are included.

Backup retention must be bounded. Deletion documentation must explain whether
deleted data remains in an existing encrypted backup, when that backup expires,
and how restoration prevents deleted state from silently becoming active
again.

The initial implementation may operate without application-managed backup
until the backup and restoration workflow is documented and tested.

### Portability

Persistent-state paths are supplied through configuration rather than
hard-coded to a machine-specific location. The database and other approved
persistent state must be movable from Brad's current Mac to a future Mac mini
while preserving correction history, provenance, and schema version.

## Consequences

### Positive

- SQLite provides transactional state with little operational burden.
- The database fits the accepted one-process, one-user deployment.
- Correction and disposition history remains inspectable.
- Backup and migration use a portable application-owned data boundary.
- Source-data duplication is reduced.
- Retention and deletion requirements are explicit and testable.

### Negative

- SQLite has limited concurrent-write scaling.
- Schema migrations require careful design, testing, and recovery planning.
- Deletion and backup propagation require explicit operational procedures.
- Minimal source persistence may require records to be fetched again.
- Reproducing a past inference may be limited after source content expires or
  changes.
- A future hosted or multi-user product may require a different database.

### Follow-up

- Define the schema and migration process during implementation without
  weakening these lifecycle boundaries.
- Document inspection, deletion, reset, backup, restoration, and migration
  procedures before relying on them operationally.
- Require every connector specification to define any caching exception and
  source-specific retention behavior.
- Verify baseline host protection before storing private runtime data.

## Guardrails

- SQLite does not become a shadow replacement for authoritative source
  systems.
- Do not persist data merely because it is available.
- Do not put database files, backups, production fixtures, tokens, or private
  exports in Git.
- Retention must be enforceable rather than merely documented.
- Derived data must remain traceable to source evidence and processing
  versions.
- Deletion must be testable.

## Related records and documents

- [ADR-0003: Adopt a Local-First Python Runtime](0003-adopt-local-first-python-runtime.md)
- [Daily Briefing v1](../product/features/daily-briefing-v1.md)
- [Constitution](../foundations/constitution.md)
- [Architecture Overview](../architecture/overview.md)
